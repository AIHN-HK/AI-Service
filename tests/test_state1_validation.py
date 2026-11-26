"""
Test validation bộ 3 hobby trong update_user_profile
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state1_validation.py
"""
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Mock external modules
sys.modules['langmem'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.models'] = MagicMock()

# Base profile for tests
BASE_PROFILE = {
    'profile_data': {
        'state_tracker': {
            'current_state': 'STATE_1_SELF_DISCOVERY',
            'current_node': 's1_explore',
            'missing_critical_slots': ['considering_careers', 'hobbies', 'strengths'],
            'completed_slots': [],
            'turn_count_in_state': 0,
            'ai_working_notes': '',
            'awaiting_task': None,
        },
        'self_understanding': {'hobbies': [], 'strengths': []},
        'career_orientation': {}
    }
}


def make_mock_db(profile=None):
    import copy
    current_profile = copy.deepcopy(profile or BASE_PROFILE)
    mock_db = AsyncMock()
    mock_db.get_user_profile = AsyncMock(return_value=copy.deepcopy(current_profile))
    mock_db.save_user_profile = AsyncMock(return_value=True)
    return mock_db


async def run_tests():
    print("\n" + "="*60)
    print("  TEST VALIDATION BỘ 3 HOBBY — State 1")
    print("="*60)
    passed = 0
    failed = 0

    with patch('app.core.features.user_tools.get_async_mongodb_service') as mock_get_db:
        from app.core.features.user_tools import update_user_profile, advance_state

        # ── TEST 1: Hobby thiếu specific_event → REJECT ──
        mock_get_db.return_value = make_mock_db()
        result = await update_user_profile.ainvoke({
            "user_id": "test",
            "updates": '{"self_understanding": {"hobbies": [{"name": "ve_tranh", "reason": "thich", "emotion": "vui"}]}}'
        })
        if "REJECTED" in result and "specific_event" in result:
            print("✅ Test 1 PASS: Thiếu specific_event → REJECTED")
            passed += 1
        else:
            print(f"❌ Test 1 FAIL: {result[:150]}")
            failed += 1

        # ── TEST 2: Hobby thiếu reason → REJECT ──
        mock_get_db.return_value = make_mock_db()
        result = await update_user_profile.ainvoke({
            "user_id": "test",
            "updates": '{"self_understanding": {"hobbies": [{"name": "ve_tranh", "specific_event": "ve tu lop 5", "emotion": "vui"}]}}'
        })
        if "REJECTED" in result and "reason" in result:
            print("✅ Test 2 PASS: Thiếu reason → REJECTED")
            passed += 1
        else:
            print(f"❌ Test 2 FAIL: {result[:150]}")
            failed += 1

        # ── TEST 3: Hobby đủ bộ 3 → ACCEPT (is_complete=True) ──
        mock_get_db.return_value = make_mock_db()
        result = await update_user_profile.ainvoke({
            "user_id": "test",
            "updates": '{"self_understanding": {"hobbies": [{"name": "ve_tranh", "specific_event": "ve tu lop 5", "reason": "thich ve", "emotion": "vui va say me"}]}}'
        })
        if "REJECTED" not in result:
            print("✅ Test 3 PASS: Đủ bộ 3 → ACCEPTED")
            passed += 1
        else:
            print(f"❌ Test 3 FAIL: {result[:150]}")
            failed += 1

        # ── TEST 4: Đánh dấu completed_slots hobbies khi chưa đủ 2 is_complete → REJECT ──
        one_hobby_profile = {
            'profile_data': {
                'state_tracker': {
                    'current_state': 'STATE_1_SELF_DISCOVERY',
                    'current_node': 's1_explore',
                    'missing_critical_slots': ['hobbies', 'strengths'],
                    'completed_slots': [],
                    'turn_count_in_state': 5,
                    'ai_working_notes': '',
                    'awaiting_task': None,
                },
                'self_understanding': {
                    'hobbies': [
                        {'name': 've_tranh', 'specific_event': 've tu lop 5',
                         'reason': 'thich', 'emotion': 'vui', 'is_complete': True}
                    ],
                    'strengths': []
                },
                'career_orientation': {}
            }
        }
        mock_get_db.return_value = make_mock_db(one_hobby_profile)
        result = await update_user_profile.ainvoke({
            "user_id": "test",
            "updates": "{}",
            "completed_slots": '["hobbies"]'
        })
        if "REJECTED" in result and "1/2" in result:
            print("✅ Test 4 PASS: Chỉ có 1/2 hobby is_complete → REJECTED khi mark hobbies done")
            passed += 1
        else:
            print(f"❌ Test 4 FAIL: {result[:150]}")
            failed += 1

        # ── TEST 5: advance_state bị BLOCK khi s1_explore chưa đủ ──
        mock_get_db.return_value = make_mock_db()  # profile rỗng, 0 hobby
        result = await advance_state.ainvoke({"user_id": "test"})
        if "BLOCKED" in result:
            print("✅ Test 5 PASS: advance_state bị BLOCK khi chưa đủ điều kiện S1")
            passed += 1
        else:
            print(f"❌ Test 5 FAIL (advance_state không block): {result[:150]}")
            failed += 1

    print(f"\n{'─'*60}")
    print(f"  KẾT QUẢ: {passed}/{passed+failed} test passed")
    if failed == 0:
        print("  🎉 TẤT CẢ PASS!")
    else:
        print(f"  ⚠️  {failed} test FAILED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(run_tests())
