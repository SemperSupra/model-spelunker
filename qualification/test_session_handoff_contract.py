#!/usr/bin/env python3
"""R45 synthetic multi-device reattach/ordered replay and authority negative oracles."""
from __future__ import annotations
import copy
import hashlib
import json
from qualification.human_io.session_handoff_contract import (
    CONTEXT_SLOTS, check_snapshot, make_reattach, manifest_digest, observe_replay
)

def digest(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

def snapshot():
    context = {name: {"ref": name + ":opaque-1",
                      "digest": digest("opaque-source-" + name), "revision": 7}
               for name in CONTEXT_SLOTS}
    return {
        "schema": "actor-cross-device-session-snapshot/v1",
        "session": {"id": "same-session-1", "owner_scope": "principal-scope-1",
                    "revision": 7, "last_event_seq": 3,
                    "context_digest": manifest_digest(context), "run_state": "paused"},
        "context": context,
        "presentation": {"portable": True, "device_local_preferences": True,
                         "content_truncated": False},
        "admission": {"authenticated_by_external_service": False,
                      "grants_tool_authority": False,
                      "carries_approval_token": False, "production_admitted": False},
    }

def page(s, records, after, more):
    return {"schema": "actor-session-replay-page/v1",
            "session_id": s["session"]["id"],
            "revision": s["session"]["revision"],
            "context_digest": s["session"]["context_digest"],
            "events": records,
            "next_seq": after + len(records),
            "has_more": more}

def event(n):
    return {"seq": n, "kind": "message" if n % 2 else "tool-result",
            "digest": digest("synthetic-event-" + str(n))}

def rejects(action):
    try: action()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("unsafe replay or unauthorized session operation accepted")

def main():
    s = snapshot()
    assert check_snapshot(s)["context_slots"] == 9
    phone = make_reattach(s, 0)
    desktop = make_reattach(s, 0)
    tablet = make_reattach(s, 0)
    assert phone == desktop == tablet
    assert "device" not in phone and "token" not in phone
    complete = page(s, [event(1), event(2), event(3)], 0, False)
    receipts = [observe_replay(s, req, complete) for req in (phone, desktop, tablet)]
    assert receipts[0] == receipts[1] == receipts[2]
    assert receipts[0]["caught_up"] is True
    assert receipts[0]["context_digest"] == s["session"]["context_digest"]
    assert not receipts[0]["approval_transferred"]
    assert not receipts[0]["tool_authority_granted"]
    assert not receipts[0]["remote_authentication_verified"]

    first = observe_replay(s, phone, page(s, [event(1)], 0, True))
    last = observe_replay(s, make_reattach(s, first["next_seq"]),
                          page(s, [event(2), event(3)], 1, False))
    assert last["caught_up"] and last["next_seq"] == 3

    updated = copy.deepcopy(s)
    updated["context"]["workspace"]["revision"] = 8
    updated["session"]["revision"] = 8
    updated["session"]["context_digest"] = manifest_digest(updated["context"])
    assert check_snapshot(updated)["revision"] == 8
    # A stale client MUST fetch the authoritative snapshot, not silently replay.
    rejects(lambda: observe_replay(s, phone, page(updated, [event(1)], 0, True)))

    bad = copy.deepcopy(s); bad["context"]["memory"]["digest"] = digest("tampered")
    bad_owner = copy.deepcopy(s); bad_owner["session"]["owner_scope"] = "other-scope"
    bad_claim = copy.deepcopy(s); bad_claim["admission"]["grants_tool_authority"] = True
    bad_auth = copy.deepcopy(s); bad_auth["admission"]["authenticated_by_external_service"] = True
    bad_token = copy.deepcopy(s); bad_token["admission"]["carries_approval_token"] = True
    bad_ctx = copy.deepcopy(s); bad_ctx["context"]["approvals"]["token"] = "do-not-copy"
    bad_presentation = copy.deepcopy(s); bad_presentation["presentation"]["content_truncated"] = True
    wrong_scope = copy.deepcopy(s); wrong_scope["session"]["owner_scope"] = ""
    bad_page = page(s, [event(1), event(3)], 0, True)
    dup_page = page(s, [event(1), event(1)], 0, True)
    forged = page(s, [event(1)], 0, True); forged["approved"] = True
    wrong_digest_page = page(s, [event(1)], 0, True); wrong_digest_page["events"][0]["digest"] = "broken"
    wrong_session_page = page(s, [event(1)], 0, True); wrong_session_page["session_id"] = "other"
    wrong_cursor_page = page(s, [event(1)], 0, True); wrong_cursor_page["next_seq"] = 2
    no_more_page = page(s, [event(1)], 0, False)
    negative = [
        lambda: check_snapshot(bad),
        lambda: check_snapshot(bad_claim),
        lambda: check_snapshot(bad_auth),
        lambda: check_snapshot(bad_token),
        lambda: check_snapshot(bad_ctx),
        lambda: check_snapshot(bad_presentation),
        lambda: check_snapshot(wrong_scope),
        lambda: make_reattach(s, -1),
        lambda: make_reattach(s, 4),
        lambda: observe_replay(s, phone, bad_page),
        lambda: observe_replay(s, phone, dup_page),
        lambda: observe_replay(s, phone, forged),
        lambda: observe_replay(s, phone, wrong_digest_page),
        lambda: observe_replay(s, phone, wrong_session_page),
        lambda: observe_replay(s, phone, wrong_cursor_page),
        lambda: observe_replay(s, phone, no_more_page),
        lambda: observe_replay(s, {**phone, "approve": True}, complete),
    ]
    for action in negative:
        rejects(action)
    # An opaque scope in the record still needs EXTERNAL authentication; this
    # critic cannot compare it with a real account or independently assert it.
    assert bad_owner["session"]["owner_scope"] != s["session"]["owner_scope"]
    print(json.dumps({"status": "PASS", "devices": 3,
                      "context_slots": len(CONTEXT_SLOTS),
                      "negative_controls": len(negative),
                      "real_authentication": False, "real_session_backend": False,
                      "tools_or_approval_transferred": False,
                      "production_admitted": False}, sort_keys=True))

if __name__ == "__main__":
    main()
