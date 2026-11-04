from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
from threading import Lock
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .action_router import ActionRouter
from .actions import Action, ActionRequest, ActionSource
from .babybuddy import BabyBuddyClient, BabyBuddyConfig, BabyBuddyError
from .dashscope_speech import DashScopeSpeechTranscriber
from .domain import InvalidTransition
from .easyinput_audio import EasyInputAudioReceiver
from .easyinput_ble import EasyInputBleFeedback
from .easyinput_hid import EasyInputHidListener
from .easyinput_protocol import (
    USB_PID,
    USB_VID,
    AgentStatus,
    SpeakerCue,
    action_uuid_for_key,
)
from .feedback import (
    FAILED_FEEDBACK_TTL_MS,
    FeedbackEvent,
    FeedbackRouter,
    FeedbackState,
)
from .macos_speech import SpeechTranscriptionError
from .storage import OperationStore, OperationStatus, SQLiteStore
from .service import BabyTapEngine
from .sync import BabyBuddySynchronizer
from .voice import VoiceDraft, VoiceParseError, parse_voice


data_path = Path(
    os.getenv(
        "BABYTAP_DB_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "babytap.sqlite3"),
    )
)
store = SQLiteStore(data_path)
engine = BabyTapEngine(store, store)
feedback = FeedbackRouter()
SOLID_FOOD_AUTO_SAVE_CONFIDENCE = 0.65


def _requires_voice_confirmation(
    context: Optional[str], confidence: Optional[float], sequence_gaps: int = 0
) -> bool:
    return context == "solid_food" and (
        (confidence is not None and confidence < SOLID_FOOD_AUTO_SAVE_CONFIDENCE)
        or sequence_gaps > 0
    )


def _build_babybuddy_client() -> Optional[BabyBuddyClient]:
    base_url = os.getenv("BABYTAP_BABYBUDDY_URL", "").strip()
    token = os.getenv("BABYTAP_BABYBUDDY_TOKEN", "").strip()
    child_id = os.getenv("BABYTAP_BABYBUDDY_CHILD_ID", "").strip()
    if not (base_url and token and child_id):
        return None
    return BabyBuddyClient(
        BabyBuddyConfig(
            base_url=base_url,
            token=token,
            child_id=int(child_id),
            bottle_type=os.getenv("BABYTAP_BOTTLE_TYPE", "breast milk"),
        )
    )


babybuddy_client = _build_babybuddy_client()
synchronizer = (
    BabyBuddySynchronizer(store, store, babybuddy_client)
    if babybuddy_client is not None
    else None
)
operation_store: Optional[OperationStore] = store
action_router = ActionRouter(engine, feedback, synchronizer, store, store)
static_index = Path(__file__).resolve().parents[2] / "static" / "index.html"
static_device = Path(__file__).resolve().parents[2] / "static" / "device.html"
static_webhid = Path(__file__).resolve().parents[2] / "static" / "easyinput-webhid.js"
_hardware_result_lock = Lock()
_hardware_last_result: Optional[dict] = None


_AGENT_STATUS = {
    FeedbackState.IDLE: AgentStatus.IDLE,
    FeedbackState.RUNNING: AgentStatus.RUNNING,
    FeedbackState.WAITING_USER: AgentStatus.WAITING_USER,
    FeedbackState.COMPLETED: AgentStatus.COMPLETED_UNREAD,
    FeedbackState.FAILED: AgentStatus.FAILED,
}


def _send_hardware_feedback(event: FeedbackEvent) -> None:
    hardware.send_agent_status(_AGENT_STATUS[event.state], event.ttl_ms, event.cue)
    ble_feedback.send_agent_status(_AGENT_STATUS[event.state], event.ttl_ms, event.cue)


def _on_hardware_key(key: int) -> None:
    global _hardware_last_result
    try:
        result = action_router.dispatch_key(
            key,
            source=ActionSource.EASYINPUT,
            occurred_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        result = {"error": str(exc), "key": key}
    with _hardware_result_lock:
        _hardware_last_result = result


hardware = EasyInputHidListener(
    _on_hardware_key,
    enabled=os.getenv("BABYTAP_ENABLE_HID", "0") == "1",
)
ble_feedback = EasyInputBleFeedback(
    enabled=os.getenv("BABYTAP_ENABLE_BLE_FEEDBACK", "1") == "1",
    device_identifier=os.getenv("BABYTAP_BLE_DEVICE_ID") or None,
)
feedback.add_sink(_send_hardware_feedback)
audio = EasyInputAudioReceiver(
    bind_host=os.getenv("BABYTAP_AUDIO_BIND", "0.0.0.0"),
    port=int(os.getenv("BABYTAP_AUDIO_PORT", "17333")),
)
audio_enabled = os.getenv("BABYTAP_ENABLE_AUDIO", "0") == "1"
speech_transcriber = DashScopeSpeechTranscriber(
    Path(
        os.getenv(
            "BABYTAP_DASHSCOPE_KEY_PATH",
            "~/Library/Application Support/BabyTap/dashscope.env",
        )
    )
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hardware.start()
    ble_feedback.start()
    # Claim the rotary encoder for BabyTap speaker volume as soon as the
    # companion starts, without waiting for the first business action.
    _send_hardware_feedback(FeedbackEvent(FeedbackState.IDLE, 0))
    if audio_enabled:
        audio.start()
    try:
        yield
    finally:
        audio.stop()
        ble_feedback.stop()
        hardware.stop()


app = FastAPI(title="BabyTap", version="0.1.0", lifespan=lifespan)


def set_engine(
    new_engine: BabyTapEngine,
    *,
    new_synchronizer: Optional[BabyBuddySynchronizer] = None,
    new_operation_store: Optional[OperationStore] = None,
    new_babybuddy_client: Optional[BabyBuddyClient] = None,
) -> None:
    """Replace runtime state for tests without leaving a stale ActionRouter."""

    global engine, action_router, synchronizer, operation_store, babybuddy_client
    engine = new_engine
    synchronizer = new_synchronizer
    operation_store = new_operation_store
    babybuddy_client = new_babybuddy_client
    feedback.reset()
    action_router = ActionRouter(
        engine,
        feedback,
        synchronizer,
        operation_store,
        operation_store,
    )


class VoiceTranscriptRequest(BaseModel):
    transcript: str


class ResetRecordsRequest(BaseModel):
    record_ids: list[UUID]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_index)


@app.get("/device")
def device_page() -> FileResponse:
    return FileResponse(static_device)


@app.get("/static/easyinput-webhid.js")
def webhid_script() -> FileResponse:
    return FileResponse(static_webhid, media_type="application/javascript")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": "0.2.0",
        "database": "ok",
        "babybuddy_configured": babybuddy_client is not None,
    }


@app.get("/api/state")
def state() -> dict:
    result = engine.snapshot()
    result["device"] = hardware.snapshot()
    result["device"]["ble_feedback"] = ble_feedback.snapshot()
    result["audio"] = audio.snapshot()
    result["speech"] = speech_transcriber.status()
    result["feedback"] = feedback.snapshot()
    result["babybuddy"] = {
        "configured": babybuddy_client is not None,
        "child_id": (
            babybuddy_client.config.child_id if babybuddy_client is not None else None
        ),
    }
    with _hardware_result_lock:
        result["last_hardware_result"] = _hardware_last_result
    return result


@app.get("/api/device")
def device_state() -> dict:
    return hardware.snapshot()


def _suggested_lan_ipv4() -> Optional[str]:
    """Return the current route's LAN address without sending network data."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        return address if address and not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        probe.close()


@app.get("/api/device/manifest")
def device_manifest() -> dict:
    return {
        "name": "EasyInput AI",
        "vendor_id": USB_VID,
        "product_id": USB_PID,
        "usage_page": 0xFF00,
        "usage": 0x02,
        "audio_port": audio.snapshot()["port"],
        "suggested_audio_host": _suggested_lan_ipv4(),
        "key_actions": {
            str(key): action_uuid_for_key(key) for key in range(1, 9)
        },
    }


@app.get("/api/audio")
def audio_state() -> dict:
    return audio.snapshot()


@app.post("/api/audio/capture/start")
def audio_capture_start() -> dict:
    try:
        session_id = audio.begin_capture()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session_id": session_id, "status": "starting"}


@app.post("/api/audio/capture/stop")
def audio_capture_stop() -> dict:
    return audio.end_capture()


@app.post("/api/voice/keyboard/start")
def keyboard_voice_start() -> dict:
    if engine.pending_voice is None:
        raise HTTPException(status_code=409, detail="请先按 K3 或 K4 启动语音录入")
    try:
        session_id = audio.begin_capture()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session_id": session_id, "status": "listening"}


@app.post("/api/voice/keyboard/stop")
def keyboard_voice_stop() -> dict:
    if engine.pending_voice is None:
        raise HTTPException(status_code=409, detail="当前没有等待录入的语音事项")
    capture = audio.end_capture()
    pcm = audio.take_pcm()
    sample_rate = int(capture.get("sample_rate") or 0)
    context = engine.pending_voice
    try:
        transcription = speech_transcriber.transcribe_pcm_result(pcm, sample_rate)
    except SpeechTranscriptionError as exc:
        feedback.publish(
            FeedbackEvent(
                FeedbackState.FAILED,
                FAILED_FEEDBACK_TTL_MS,
                str(exc),
                SpeakerCue.FAILED,
            )
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    confidence = transcription.confidence
    return {
        "transcript": transcription.transcript,
        "confidence": confidence,
        "requires_confirmation": _requires_voice_confirmation(
            context,
            confidence,
            int(capture.get("sequence_gaps") or 0),
        ),
        "capture": capture,
    }


@app.post("/api/voice/computer/transcribe")
async def computer_voice_transcribe(request: Request, sample_rate: int) -> dict:
    if engine.pending_voice is None:
        raise HTTPException(status_code=409, detail="请先按 K3 或 K4 启动语音录入")
    if sample_rate < 8000 or sample_rate > 96000:
        raise HTTPException(status_code=422, detail="电脑麦克风采样率无效")
    pcm = await request.body()
    if not pcm or len(pcm) % 2:
        raise HTTPException(status_code=422, detail="没有收到有效的电脑麦克风录音")
    if len(pcm) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="电脑麦克风录音过长")
    context = engine.pending_voice
    try:
        transcription = speech_transcriber.transcribe_pcm_result(pcm, sample_rate)
    except SpeechTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "transcript": transcription.transcript,
        "confidence": transcription.confidence,
        "requires_confirmation": _requires_voice_confirmation(
            context, transcription.confidence
        ),
        "sample_rate": sample_rate,
        "pcm_bytes": len(pcm),
    }


@app.post("/api/keys/{key}")
def key_press(key: int) -> dict:
    return _dispatch_key(key, ActionSource.WEB)


@app.post("/api/device/keys/{key}")
def device_key_press(key: int) -> dict:
    """Receive a physical EasyInput key forwarded by the WebHID adapter."""

    return _dispatch_key(key, ActionSource.EASYINPUT)


def _dispatch_key(key: int, source: ActionSource) -> dict:
    try:
        result = action_router.dispatch_key(
            key,
            source=source,
            occurred_at=datetime.now(timezone.utc),
        )
        return result
    except (InvalidTransition, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/actions/{action}")
def action_dispatch(action: Action) -> dict:
    try:
        result = action_router.dispatch(
            ActionRequest.create(
                action,
                ActionSource.WEB,
                occurred_at=datetime.now(timezone.utc),
            )
        )
        return result
    except (InvalidTransition, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/voice/transcript")
def voice_transcript(request: VoiceTranscriptRequest) -> dict:
    context = engine.pending_voice
    if context is None:
        raise HTTPException(status_code=409, detail="请先按 K3 或 K4 启动语音录入")
    try:
        draft = VoiceDraft(
            context,
            request.transcript.strip(),
            parse_voice(context, request.transcript),
        )
    except VoiceParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "needs_confirmation", "draft": draft.as_dict()}


@app.post("/api/voice/confirm")
def voice_confirm(request: VoiceTranscriptRequest) -> dict:
    try:
        record = engine.complete_voice_transcript(
            request.transcript, datetime.now(timezone.utc)
        )
        sync_result = action_router.finalize_record(record.record_id)
    except VoiceParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "action": "recorded",
        "kind": record.kind,
        "record_id": str(record.record_id),
        "data": record.data,
        **sync_result,
    }


@app.post("/api/voice/cancel")
def voice_cancel() -> dict:
    result = engine.cancel_pending_voice()
    feedback.publish(
        FeedbackEvent(FeedbackState.IDLE, 0, cue=SpeakerCue.CANCELLED)
    )
    return result


@app.get("/api/records")
def records() -> list:
    return [
        {
            "record_id": str(record.record_id),
            "kind": record.kind,
            "started_at": record.started_at.isoformat(),
            "ended_at": record.ended_at.isoformat(),
            "data": record.data,
        }
        for record in engine.record_store.list()
    ]


@app.post("/api/records/reset")
def reset_records(request: ResetRecordsRequest) -> dict:
    record_ids = list(dict.fromkeys(request.record_ids))
    if not record_ids:
        raise HTTPException(status_code=422, detail="没有可清空的记录")
    if len(record_ids) > 100:
        raise HTTPException(status_code=422, detail="一次最多清空 100 条记录")

    deleted = []
    failed = []
    for record_id in record_ids:
        if engine.record_store.get(record_id) is None:
            continue
        result = action_router.undo_record(record_id)
        if result["sync_status"] in {"undone", "local_only"}:
            engine.record_store.mark_undone(record_id)
            deleted.append(str(record_id))
        else:
            failed.append(
                {
                    "record_id": str(record_id),
                    "error": result.get("sync_error") or "撤销没有完成",
                }
            )

    return {
        "requested_count": len(record_ids),
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted_record_ids": deleted,
        "failed": failed,
    }


@app.get("/api/operations")
def operations() -> list:
    if operation_store is None:
        return []
    return [
        {
            "record_id": str(operation.record_id),
            "kind": operation.kind,
            "status": operation.status.value,
            "remote_count": len(operation.remote_refs),
            "attempts": operation.attempts,
            "error": operation.error,
            "created_at": operation.created_at.isoformat(),
            "updated_at": operation.updated_at.isoformat(),
        }
        for operation in operation_store.list_operations()
    ]


@app.post("/api/operations/{record_id}/retry")
def retry_operation(record_id: UUID) -> dict:
    if synchronizer is None:
        raise HTTPException(status_code=409, detail="Baby Buddy 尚未配置")
    outcome = synchronizer.retry(record_id)
    if outcome.status is OperationStatus.SYNCED:
        feedback.publish(
            FeedbackEvent(
                FeedbackState.COMPLETED,
                5000,
                "重试成功",
                SpeakerCue.RECORD_SAVED,
            )
        )
    elif outcome.status is OperationStatus.UNDONE:
        engine.record_store.mark_undone(record_id)
        feedback.publish(
            FeedbackEvent(
                FeedbackState.COMPLETED,
                5000,
                "撤销重试成功",
                SpeakerCue.UNDONE,
            )
        )
    else:
        feedback.publish(
            FeedbackEvent(
                FeedbackState.FAILED,
                FAILED_FEEDBACK_TTL_MS,
                outcome.error,
                SpeakerCue.FAILED,
            )
        )
    return outcome.as_dict()


@app.get("/api/babybuddy/check")
def babybuddy_check() -> dict:
    if babybuddy_client is None:
        return {"configured": False, "connected": False}
    try:
        return {"configured": True, **babybuddy_client.check()}
    except BabyBuddyError as exc:
        return {"configured": True, "connected": False, "error": str(exc)}
