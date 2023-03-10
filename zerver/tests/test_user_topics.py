from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest import mock

from django.db import transaction
from django.utils.timezone import now as timezone_now

from zerver.actions.user_topics import do_set_user_topic_visibility_policy
from zerver.lib.stream_topic import StreamTopicTarget
from zerver.lib.test_classes import ZulipTestCase
from zerver.lib.user_topics import (
    get_topic_mutes,
    topic_is_muted,
)
from zerver.models import UserProfile, UserTopic, get_stream


class MutedTopicsTests(ZulipTestCase):
    def test_get_deactivated_muted_topic(self) -> None:
        user = self.example_user("hamlet")
        self.login_user(user)

        stream = get_stream("Verona", user.realm)

        mock_date_muted = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()

        do_set_user_topic_visibility_policy(
            user,
            stream,
            "Verona3",
            visibility_policy=UserTopic.MUTED,
            last_updated=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

        stream.deactivated = True
        stream.save()

        self.assertNotIn((stream.name, "Verona3", mock_date_muted), get_topic_mutes(user))
        self.assertIn((stream.name, "Verona3", mock_date_muted), get_topic_mutes(user, True))

    def test_user_ids_muting_topic(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        realm = hamlet.realm
        stream = get_stream("Verona", realm)
        topic_name = "teST topic"
        date_muted = datetime(2020, 1, 1, tzinfo=timezone.utc)

        stream_topic_target = StreamTopicTarget(
            stream_id=stream.id,
            topic_name=topic_name,
        )

        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.MUTED)
        self.assertEqual(user_ids, set())

        def mute_topic_for_user(user: UserProfile) -> None:
            do_set_user_topic_visibility_policy(
                user,
                stream,
                "test TOPIC",
                visibility_policy=UserTopic.MUTED,
                last_updated=date_muted,
            )

        mute_topic_for_user(hamlet)
        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.MUTED)
        self.assertEqual(user_ids, {hamlet.id})
        hamlet_date_muted = UserTopic.objects.filter(
            user_profile=hamlet, visibility_policy=UserTopic.MUTED
        )[0].last_updated
        self.assertEqual(hamlet_date_muted, date_muted)

        mute_topic_for_user(cordelia)
        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.MUTED)
        self.assertEqual(user_ids, {hamlet.id, cordelia.id})
        cordelia_date_muted = UserTopic.objects.filter(
            user_profile=cordelia, visibility_policy=UserTopic.MUTED
        )[0].last_updated
        self.assertEqual(cordelia_date_muted, date_muted)

    def test_add_muted_topic(self) -> None:
        user = self.example_user("hamlet")
        self.login_user(user)

        stream = get_stream("Verona", user.realm)

        url = "/api/v1/users/me/subscriptions/muted_topics"

        payloads: List[Dict[str, object]] = [
            {"stream": stream.name, "topic": "Verona3", "op": "add"},
            {"stream_id": stream.id, "topic": "Verona3", "op": "add"},
        ]

        mock_date_muted = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        for data in payloads:
            with mock.patch(
                "zerver.views.user_topics.timezone_now",
                return_value=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ):
                result = self.api_patch(user, url, data)
                self.assert_json_success(result)

            self.assertIn((stream.name, "Verona3", mock_date_muted), get_topic_mutes(user))
            self.assertTrue(topic_is_muted(user, stream.id, "verona3"))

            do_set_user_topic_visibility_policy(
                user,
                stream,
                "Verona3",
                visibility_policy=UserTopic.VISIBILITY_POLICY_INHERIT,
            )

        assert stream.recipient is not None
        result = self.api_patch(user, url, data)

        # Now check that error is raised when attempted to mute an already
        # muted topic. This should be case-insensitive.
        data["topic"] = "VERONA3"
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Topic already muted")

    def test_remove_muted_topic(self) -> None:
        user = self.example_user("hamlet")
        realm = user.realm
        self.login_user(user)

        stream = get_stream("Verona", realm)

        url = "/api/v1/users/me/subscriptions/muted_topics"
        payloads: List[Dict[str, object]] = [
            {"stream": stream.name, "topic": "vERONA3", "op": "remove"},
            {"stream_id": stream.id, "topic": "vEroNA3", "op": "remove"},
        ]
        mock_date_muted = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()

        for data in payloads:
            do_set_user_topic_visibility_policy(
                user,
                stream,
                "Verona3",
                visibility_policy=UserTopic.MUTED,
                last_updated=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
            self.assertIn((stream.name, "Verona3", mock_date_muted), get_topic_mutes(user))

            result = self.api_patch(user, url, data)

            self.assert_json_success(result)
            self.assertNotIn((stream.name, "Verona3", mock_date_muted), get_topic_mutes(user))
            self.assertFalse(topic_is_muted(user, stream.id, "verona3"))

    def test_muted_topic_add_invalid(self) -> None:
        user = self.example_user("hamlet")
        realm = user.realm
        self.login_user(user)

        stream = get_stream("Verona", realm)
        do_set_user_topic_visibility_policy(
            user, stream, "Verona3", visibility_policy=UserTopic.MUTED, last_updated=timezone_now()
        )

        url = "/api/v1/users/me/subscriptions/muted_topics"

        data = {"stream_id": 999999999, "topic": "Verona3", "op": "add"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Invalid stream ID")

        data = {"topic": "Verona3", "op": "add"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Please supply 'stream'.")

        data = {"stream": stream.name, "stream_id": stream.id, "topic": "Verona3", "op": "add"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Please choose one: 'stream' or 'stream_id'.")

    def test_muted_topic_remove_invalid(self) -> None:
        user = self.example_user("hamlet")
        realm = user.realm
        self.login_user(user)
        stream = get_stream("Verona", realm)

        url = "/api/v1/users/me/subscriptions/muted_topics"
        data: Dict[str, Any] = {"stream": "BOGUS", "topic": "Verona3", "op": "remove"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Topic is not muted")

        with transaction.atomic():
            # This API call needs a new nested transaction with 'savepoint=True',
            # because it calls 'set_user_topic_visibility_policy_in_database',
            # which on failure rollbacks the test-transaction.
            # If it is not used, the test-transaction will be rolled back during this API call,
            # and the next API call will result in a "TransactionManagementError."
            data = {"stream": stream.name, "topic": "BOGUS", "op": "remove"}
            result = self.api_patch(user, url, data)
            self.assert_json_error(result, "Nothing to be done")

        data = {"stream_id": 999999999, "topic": "BOGUS", "op": "remove"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Topic is not muted")

        data = {"topic": "Verona3", "op": "remove"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Please supply 'stream'.")

        data = {"stream": stream.name, "stream_id": stream.id, "topic": "Verona3", "op": "remove"}
        result = self.api_patch(user, url, data)
        self.assert_json_error(result, "Please choose one: 'stream' or 'stream_id'.")


class UnmutedTopicsTests(ZulipTestCase):
    def test_user_ids_unmuting_topic(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        realm = hamlet.realm
        stream = get_stream("Verona", realm)
        topic_name = "teST topic"
        date_unmuted = datetime(2020, 1, 1, tzinfo=timezone.utc)

        stream_topic_target = StreamTopicTarget(
            stream_id=stream.id,
            topic_name=topic_name,
        )

        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.UNMUTED)
        self.assertEqual(user_ids, set())

        def set_topic_visibility_for_user(user: UserProfile, visibility_policy: int) -> None:
            do_set_user_topic_visibility_policy(
                user,
                stream,
                "test TOPIC",
                visibility_policy=visibility_policy,
                last_updated=date_unmuted,
            )

        set_topic_visibility_for_user(hamlet, UserTopic.UNMUTED)
        set_topic_visibility_for_user(cordelia, UserTopic.MUTED)
        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.UNMUTED)
        self.assertEqual(user_ids, {hamlet.id})
        hamlet_date_unmuted = UserTopic.objects.filter(
            user_profile=hamlet, visibility_policy=UserTopic.UNMUTED
        )[0].last_updated
        self.assertEqual(hamlet_date_unmuted, date_unmuted)

        set_topic_visibility_for_user(cordelia, UserTopic.UNMUTED)
        user_ids = stream_topic_target.user_ids_with_visibility_policy(UserTopic.UNMUTED)
        self.assertEqual(user_ids, {hamlet.id, cordelia.id})
        cordelia_date_unmuted = UserTopic.objects.filter(
            user_profile=cordelia, visibility_policy=UserTopic.UNMUTED
        )[0].last_updated
        self.assertEqual(cordelia_date_unmuted, date_unmuted)
