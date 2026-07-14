#!/usr/bin/env python3
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from channels import mattermost


def load_mattermost():
    return importlib.reload(mattermost)


def test_messages_are_buffered_until_consumed():
    mm = load_mattermost()
    mm._set_last("first")
    mm._set_last("second")
    assert mm.getLastMessage() == "first | second"
    assert mm.getLastMessage() == ""


def test_post_deduplication_is_bounded():
    mm = load_mattermost()
    assert mm._remember_post_id("post-1") is True
    assert mm._remember_post_id("post-1") is False
    for index in range(mm._MAX_SEEN_POST_IDS + 8):
        assert mm._remember_post_id(f"post-{index + 2}") is True
    assert len(mm._seen_post_ids) == mm._MAX_SEEN_POST_IDS
    assert len(mm._seen_post_id_set) == mm._MAX_SEEN_POST_IDS


if __name__ == "__main__":
    test_messages_are_buffered_until_consumed()
    test_post_deduplication_is_bounded()
