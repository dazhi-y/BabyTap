import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from babytap import main
from babytap.macos_speech import SpeechTranscription, SpeechTranscriptionError
from babytap.service import BabyTapEngine
from babytap.storage import OperationStatus
from babytap.sync import SyncOutcome


class SelectiveUndoSynchronizer:
    def __init__(self) -> None:
        self.fail_id = None

    def sync_record(self, record_id: UUID) -> SyncOutcome:
        return SyncOutcome(record_id, OperationStatus.SYNCED, 1)

    def undo_record(self, record_id: UUID) -> SyncOutcome:
        if record_id == self.fail_id:
            return SyncOutcome(record_id, OperationStatus.UNDO_FAILED, 1, "远端失败")
        return SyncOutcome(record_id, OperationStatus.UNDONE, 0)

    def retry(self, record_id: UUID) -> SyncOutcome:
        return self.undo_record(record_id)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        main.set_engine(BabyTapEngine())
        self.client = TestClient(main.app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_device_guide_page_and_manifest(self) -> None:
        page = self.client.get("/device")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("USB 与 Wi‑Fi 双通道识别", page.text)
        self.assertNotIn('id="device-title"', page.text)
        self.assertIn("BabyTap 固定键位", page.text)
        self.assertIn("说明记录台中的实际作用", page.text)
        self.assertIn("任意侧开始；按另一侧换边；再次按当前侧结束并保存", page.text)
        self.assertIn("说出毫升数后自动保存；也可手动输入", page.text)
        self.assertIn("说出辅食内容后自动保存；也可手动输入", page.text)
        self.assertIn("录入中取消，否则撤销最近操作", page.text)
        self.assertIn("开发板扬声器播报当前状态", page.text)
        self.assertIn("配置完成后退出官方程序", page.text)
        self.assertIn("由 BabyTap 接收板载麦克风", page.text)
        self.assertIn('aria-label="页面切换"', page.text)
        self.assertIn('<a href="/">记录台</a>', page.text)
        self.assertIn('<a class="active" href="/device" aria-current="page">按键说明</a>', page.text)
        self.assertIn("USB EasyInput", page.text)
        self.assertIn("Wi‑Fi EasyInput", page.text)
        self.assertNotIn('id="wifi-password"', page.text)
        self.assertNotIn("同步 BabyTap 配置", page.text)
        self.assertNotIn("syncConfig(", page.text)

        manifest = self.client.get("/api/device/manifest")
        self.assertEqual(manifest.status_code, 200)
        payload = manifest.json()
        self.assertEqual(payload["vendor_id"], 0x303A)
        self.assertEqual(payload["product_id"], 0x1006)
        self.assertEqual(sorted(payload["key_actions"]), [str(key) for key in range(1, 9)])
        self.assertEqual(len(set(payload["key_actions"].values())), 8)

        script = self.client.get("/static/easyinput-webhid.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("requestDevice", script.text)

    def test_any_side_can_start(self) -> None:
        response = self.client.post("/api/keys/2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "started")
        self.assertEqual(response.json()["active_side"], "right")

    def test_bottle_requests_voice(self) -> None:
        response = self.client.post("/api/keys/3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "voice_requested")

    def test_voice_cancel_never_undoes_latest_record(self) -> None:
        self.client.post("/api/keys/5")
        before = self.client.get("/api/state").json()["record_count"]

        response = self.client.post("/api/voice/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "nothing_to_cancel")
        self.assertEqual(self.client.get("/api/state").json()["record_count"], before)

    def test_webhid_key_keeps_easyinput_source(self) -> None:
        response = self.client.post("/api/device/keys/2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "started")
        self.assertEqual(response.json()["source"], "easyinput")

    def test_named_action_uses_same_router(self) -> None:
        response = self.client.post("/api/actions/breast_right")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_side"], "right")
        self.assertEqual(response.json()["input_action"], "breast_right")
        self.assertEqual(response.json()["source"], "web")

    def test_voice_text_confirmation_flow(self) -> None:
        self.client.post("/api/keys/3")
        confirmed = self.client.post(
            "/api/voice/confirm", json={"transcript": "120"}
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["kind"], "bottle")
        self.assertEqual(confirmed.json()["data"]["amount_ml"], 120)
        self.assertEqual(confirmed.json()["sync_status"], "local_only")

    def test_voice_confirmation_uses_current_text_not_preview(self) -> None:
        self.client.post("/api/keys/3")
        preview = self.client.post(
            "/api/voice/transcript", json={"transcript": "90 毫升"}
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["draft"]["data"]["amount_ml"], 90)

        confirmed = self.client.post(
            "/api/voice/confirm", json={"transcript": "120 毫升"}
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["data"]["amount_ml"], 120)

    def test_computer_microphone_pcm_uses_local_transcriber(self) -> None:
        self.client.post("/api/keys/3")
        pcm = b"\x01\x00" * 480

        with patch.object(
            main.speech_transcriber,
            "transcribe_pcm_result",
            return_value=SpeechTranscription("奶瓶一百二十毫升", 0.9),
        ) as transcribe:
            response = self.client.post(
                "/api/voice/computer/transcribe?sample_rate=48000",
                content=pcm,
                headers={"Content-Type": "application/octet-stream"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "奶瓶一百二十毫升")
        self.assertFalse(response.json()["requires_confirmation"])
        self.assertEqual(response.json()["pcm_bytes"], len(pcm))
        transcribe.assert_called_once_with(pcm, 48000)

    def test_keyboard_transcription_failure_publishes_hardware_feedback(self) -> None:
        self.client.post("/api/keys/3")
        capture = {"sample_rate": 16000, "frames": 20, "pcm_bytes": 12800}

        with (
            patch.object(main.audio, "end_capture", return_value=capture),
            patch.object(main.audio, "take_pcm", return_value=b"\x01\x00" * 6400),
            patch.object(
                main.speech_transcriber,
                "transcribe_pcm_result",
                side_effect=SpeechTranscriptionError("没有识别到有效语音"),
            ),
        ):
            response = self.client.post("/api/voice/keyboard/stop")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "没有识别到有效语音")
        state = self.client.get("/api/state").json()
        self.assertEqual(state["feedback"]["state"], "failed")
        self.assertEqual(state["feedback"]["message"], "没有识别到有效语音")

    def test_low_confidence_solid_food_requires_confirmation(self) -> None:
        self.client.post("/api/keys/4")
        capture = {
            "sample_rate": 16000,
            "frames": 20,
            "pcm_bytes": 12800,
            "sequence_gaps": 0,
        }

        with (
            patch.object(main.audio, "end_capture", return_value=capture),
            patch.object(main.audio, "take_pcm", return_value=b"\x01\x00" * 6400),
            patch.object(
                main.speech_transcriber,
                "transcribe_pcm_result",
                return_value=SpeechTranscription("炸弹", 0.4),
            ),
        ):
            response = self.client.post("/api/voice/keyboard/stop")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["requires_confirmation"])
        self.assertEqual(response.json()["transcript"], "炸弹")

    def test_solid_food_with_audio_gaps_requires_confirmation(self) -> None:
        self.client.post("/api/keys/4")
        capture = {
            "sample_rate": 16000,
            "frames": 20,
            "pcm_bytes": 12800,
            "sequence_gaps": 3,
        }

        with (
            patch.object(main.audio, "end_capture", return_value=capture),
            patch.object(main.audio, "take_pcm", return_value=b"\x01\x00" * 6400),
            patch.object(
                main.speech_transcriber,
                "transcribe_pcm_result",
                return_value=SpeechTranscription("米粉加蛋黄", 0.95),
            ),
        ):
            response = self.client.post("/api/voice/keyboard/stop")

        self.assertTrue(response.json()["requires_confirmation"])

    def test_high_confidence_solid_food_can_auto_save(self) -> None:
        self.client.post("/api/keys/4")
        capture = {
            "sample_rate": 16000,
            "frames": 20,
            "pcm_bytes": 12800,
            "sequence_gaps": 0,
        }

        with (
            patch.object(main.audio, "end_capture", return_value=capture),
            patch.object(main.audio, "take_pcm", return_value=b"\x01\x00" * 6400),
            patch.object(
                main.speech_transcriber,
                "transcribe_pcm_result",
                return_value=SpeechTranscription("米粉加蛋黄", 0.9),
            ),
        ):
            response = self.client.post("/api/voice/keyboard/stop")

        self.assertFalse(response.json()["requires_confirmation"])

    def test_dashscope_solid_food_without_confidence_can_auto_save(self) -> None:
        self.client.post("/api/keys/4")
        capture = {
            "sample_rate": 16000,
            "frames": 20,
            "pcm_bytes": 12800,
            "sequence_gaps": 0,
        }

        with (
            patch.object(main.audio, "end_capture", return_value=capture),
            patch.object(main.audio, "take_pcm", return_value=b"\x01\x00" * 6400),
            patch.object(
                main.speech_transcriber,
                "transcribe_pcm_result",
                return_value=SpeechTranscription("米粉加蛋黄", None),
            ),
        ):
            response = self.client.post("/api/voice/keyboard/stop")

        self.assertFalse(response.json()["requires_confirmation"])

    def test_computer_microphone_requires_pending_voice_action(self) -> None:
        response = self.client.post(
            "/api/voice/computer/transcribe?sample_rate=48000",
            content=b"\x00\x00" * 160,
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("K3", response.json()["detail"])

    def test_record_page_allows_direct_voice_confirmation(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("现在要记录什么？", page.text)
        self.assertNotIn('class="key-grid"', page.text)
        self.assertNotIn("BabyTap 电脑端 · 实体键盘记录 · 网页实时反馈", page.text)
        self.assertIn('aria-label="页面切换"', page.text)
        self.assertIn('<a class="active" href="/" aria-current="page">记录台</a>', page.text)
        self.assertIn('<a href="/device">按键说明</a>', page.text)
        self.assertIn('id="baby-identity"', page.text)
        self.assertIn('font-size: clamp(30px, 3.2vw, 38px)', page.text)
        self.assertIn('.brand-copy { min-width: 0; display: flex; align-items: baseline; flex-wrap: wrap;', page.text)
        self.assertIn('.baby-identity { margin: 0;', page.text)
        self.assertIn("function babyAge(birthDate, today=new Date())", page.text)
        self.assertIn("renderBabyIdentity(bbStatus);", page.text)
        self.assertIn('<dialog class="voice-dialog" id="voice-dialog"', page.text)
        self.assertIn('aria-label="奶量"', page.text)
        self.assertIn('id="voice-error"', page.text)
        self.assertIn('onclick="cancelVoice()">取消</button>', page.text)
        self.assertIn('id="confirm" onclick="confirmVoice()" disabled>确认</button>', page.text)
        self.assertIn('oninput="updateVoiceActions(true)"', page.text)
        self.assertIn("onkeydown=\"if(event.key==='Enter' && !event.isComposing) confirmVoice()\"", page.text)
        self.assertIn("result.requires_confirmation === true", page.text)
        self.assertIn("录音质量或识别把握不足", page.text)
        self.assertIn("navigator.mediaDevices.getUserMedia", page.text)
        self.assertIn("/api/voice/computer/transcribe", page.text)
        self.assertIn('id="voice-level-bar"', page.text)
        self.assertNotIn("SpeechRecognition", page.text)
        self.assertIn("currentState?.audio?.listening", page.text)
        self.assertIn("currentState.audio.device_discovered && currentState.audio.audio_ready", page.text)
        self.assertIn("await startKeyboardSpeech();", page.text)
        self.assertIn("await startComputerSpeech();", page.text)
        self.assertIn("function isVoiceStopKey(key)", page.text)
        self.assertIn("finishSpeechWindow();", page.text)
        self.assertIn("说完再按一次 ${stopKey}", page.text)
        self.assertIn("onKey: key => handlePhysicalKey(key)", page.text)
        self.assertIn("正在自动保存…", page.text)
        self.assertIn("if (input.value.trim() !== transcript) return;", page.text)
        self.assertIn("await confirmVoice();", page.text)
        self.assertIn("dialog.showModal()", page.text)
        self.assertIn("const BOARD_PROMPT_LEAD_IN_MS = 1800", page.text)
        self.assertIn("function scheduleVoiceCapture()", page.text)
        self.assertIn("正在播放板载提示音，播完后自动开始收音", page.text)
        self.assertIn("voicePromptPending && isMatchingVoiceKey(key)", page.text)
        self.assertNotIn("setTimeout(startSpeech, 120)", page.text)
        self.assertIn("`${data.amount_ml} 毫升`", page.text)
        self.assertIn("requestId !== refreshRequestId", page.text)
        self.assertIn("currentState.pending_voice = null", page.text)
        self.assertIn("body:JSON.stringify({transcript})", page.text)
        self.assertNotIn(">解析文字</button>", page.text)
        self.assertNotIn("重新听 15 秒</button>", page.text)
        self.assertIn('id="reset-day"', page.text)
        self.assertIn("已经同步的记录也会从育儿记录库撤销", page.text)
        self.assertIn('id="summary-period"', page.text)
        self.assertIn('<h2 id="state-label">当前状态</h2>', page.text)
        self.assertIn('<h2 id="summary-period">今日概览 · 截至现在</h2>', page.text)
        self.assertIn('.summary-heading h2 {', page.text)
        self.assertIn('id="summary-bottle"', page.text)
        self.assertIn('id="summary-bottle-detail"', page.text)
        self.assertIn('id="summary-diaper-detail"', page.text)
        self.assertIn('id="summary-sleep-detail"', page.text)
        self.assertIn('id="summary-solid-food"', page.text)
        self.assertIn('id="summary-solid-food-detail"', page.text)
        self.assertIn(".daily-summary { flex: 0 0 auto;", page.text)
        self.assertIn("border: 1px solid rgba(126,105,192,.22)", page.text)
        self.assertIn("border: 1px solid rgba(92,169,139,.22)", page.text)
        self.assertIn(".main-panel { min-height: 0; overflow: hidden; }", page.text)
        self.assertIn("grid-template-columns: minmax(0, 1.06fr) minmax(0, .94fr)", page.text)
        self.assertIn(".daily-summary { flex: 1 1 auto; }", page.text)
        self.assertIn(".intervals { flex: 0 1 auto; }", page.text)
        self.assertIn(".summary-item { min-height: 0;", page.text)
        self.assertIn(".interval-item { display: flex; flex-direction: column; justify-content: center; }", page.text)
        self.assertIn("@media (min-width: 851px) and (max-height: 680px)", page.text)
        self.assertIn('id="feeding-interval"', page.text)
        self.assertIn('id="diaper-interval"', page.text)
        self.assertIn('id="sleep-interval"', page.text)
        self.assertIn('<h2 id="key-reference-title">键位备忘</h2>', page.text)
        self.assertEqual(page.text.count('class="key-reference-item"'), 8)
        self.assertIn('<kbd>K1</kbd><span>左侧母乳</span>', page.text)
        self.assertIn('<kbd>K8</kbd><span>播报状态</span>', page.text)
        self.assertIn('.key-reference-grid { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr));', page.text)
        self.assertIn('@media (min-width: 851px) and (max-width: 1100px)', page.text)
        self.assertIn('.key-reference-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); row-gap: 6px; }', page.text)
        self.assertIn('.key-reference-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }', page.text)
        self.assertIn('.key-reference { flex: 0 0 auto; padding-top: 9px; border-top: 1px solid rgba(91,77,126,.10);', page.text)
        self.assertNotIn('EasyInput K1–K8</span>', page.text)
        self.assertIn("latestRecord(records, ['breastfeeding', 'bottle'])", page.text)
        self.assertIn("record => localDateKey(record.started_at) === today", page.text)
        self.assertIn("currentState.sleep.active", page.text)
        self.assertIn("summary.breastfeedingCount += 1", page.text)
        self.assertIn("record.kind === 'solid_food'", page.text)
        self.assertIn("summary.solidFoods.join('、')", page.text)
        self.assertIn("function renderDailySummary(records)", page.text)
        self.assertIn("--event-breastfeeding: #c8bcf1", page.text)
        self.assertIn('data-kind="${record.kind}"', page.text)
        self.assertIn('.item[data-kind="sleep"] .item-mark', page.text)
        self.assertIn('class="item-line"', page.text)
        self.assertIn('.item-line .meta::before', page.text)
        self.assertIn('<span class="record-detail">${detail.extra}</span>', page.text)

    def test_reset_records_clears_only_requested_records(self) -> None:
        first = self.client.post("/api/keys/5").json()["record_id"]
        second = self.client.post("/api/keys/5").json()["record_id"]
        untouched = self.client.post("/api/keys/5").json()["record_id"]

        response = self.client.post(
            "/api/records/reset", json={"record_ids": [first, second]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_count"], 2)
        self.assertEqual(response.json()["failed_count"], 0)
        remaining = [
            record["record_id"] for record in self.client.get("/api/records").json()
        ]
        self.assertEqual(remaining, [untouched])

    def test_reset_records_rejects_an_empty_selection(self) -> None:
        response = self.client.post("/api/records/reset", json={"record_ids": []})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "没有可清空的记录")

    def test_reset_records_keeps_remote_failures_visible(self) -> None:
        sync = SelectiveUndoSynchronizer()
        main.set_engine(BabyTapEngine(), new_synchronizer=sync)
        first = self.client.post("/api/keys/5").json()["record_id"]
        failed = self.client.post("/api/keys/5").json()["record_id"]
        sync.fail_id = UUID(failed)

        response = self.client.post(
            "/api/records/reset", json={"record_ids": [first, failed]}
        )

        self.assertEqual(response.json()["deleted_count"], 1)
        self.assertEqual(response.json()["failed_count"], 1)
        remaining = [
            record["record_id"] for record in self.client.get("/api/records").json()
        ]
        self.assertEqual(remaining, [failed])

        sync.fail_id = None
        retried = self.client.post(f"/api/operations/{failed}/retry")
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["sync_status"], "undone")
        self.assertEqual(self.client.get("/api/records").json(), [])



if __name__ == "__main__":
    unittest.main()
