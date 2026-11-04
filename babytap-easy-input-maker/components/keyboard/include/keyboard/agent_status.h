#pragma once

#include <cstddef>
#include <cstdint>

namespace ai_keyboard {

constexpr std::uint8_t kAgentStatusProtocolVersion = 1;
constexpr std::uint8_t kAgentStatusReportId = 0x12;
constexpr std::size_t kAgentStatusPayloadLen = 16;
constexpr std::uint32_t kAgentStatusMaxTtlMs = 12U * 60U * 60U * 1000U;
constexpr std::uint32_t kAgentStatusAnimationFrameMs = 40U;
constexpr std::uint32_t kAgentStatusWaveFrameMs = kAgentStatusAnimationFrameMs;
constexpr std::uint8_t kAgentStatusWaveFramesPerPixel = 5U;
constexpr std::uint8_t kAgentStatusWaveTailPixels = 3U;
constexpr std::uint8_t kAgentStatusWaveScaleMax = 16U;
constexpr std::uint8_t kAgentStatusWaveScaleDenominator = 16U;
constexpr std::uint8_t kAgentStatusScannerFramesPerPixel = 4U;
constexpr std::uint8_t kAgentStatusBloomFramesPerRing = 3U;
constexpr std::uint8_t kAgentStatusBloomPauseFrames = 8U;
constexpr std::uint8_t kAgentStatusFailedCycleFrames = 30U;

enum class AgentStatusState : std::uint8_t {
  kIdle = 0,
  kRunning = 1,
  kWaitingUser = 2,
  kCompletedUnread = 3,
  kFailed = 4,
};

// The low five flag bits optionally request one short, fixed speaker cue.
// Zero preserves the original status-only protocol. Unknown values are
// ignored so older or unrelated Agent Status producers remain compatible.
inline constexpr std::uint8_t kAgentStatusCueMask = 0x1FU;
inline constexpr std::uint8_t kAgentStatusBabytapVolumeControl = 0x80U;

enum class AgentStatusCue : std::uint8_t {
  kNone = 0,
  kTimerStarted = 1,
  kSideSwitched = 2,
  kBottlePrompt = 3,
  kSolidFoodPrompt = 4,
  kDiaperRecorded = 5,
  kSleepStarted = 6,
  kRecordSaved = 7,
  kCancelled = 8,
  kUndone = 9,
  kStatusIdle = 10,
  kStatusBreastfeeding = 11,
  kStatusSleep = 12,
  kStatusWaiting = 13,
  kFailed = 14,
  kNothingToUndo = 15,
};

inline AgentStatusCue agent_status_cue(std::uint8_t flags) {
  const auto value = static_cast<std::uint8_t>(flags & kAgentStatusCueMask);
  if (value > static_cast<std::uint8_t>(AgentStatusCue::kNothingToUndo)) {
    return AgentStatusCue::kNone;
  }
  return static_cast<AgentStatusCue>(value);
}

inline bool agent_status_babytap_volume_control(std::uint8_t flags) {
  return (flags & kAgentStatusBabytapVolumeControl) != 0U;
}

inline std::uint8_t agent_status_running_wave_numerator(
    std::uint32_t now_ms,
    std::uint8_t pixel_index,
    std::uint8_t pixel_count) {
  if (pixel_count == 0U || pixel_index >= pixel_count) {
    return 0U;
  }

  const auto cycle_frames = static_cast<std::uint32_t>(
      (pixel_count + kAgentStatusWaveTailPixels) *
      kAgentStatusWaveFramesPerPixel);
  const auto phase = (now_ms / kAgentStatusWaveFrameMs) % cycle_frames;
  const auto pixel_phase = static_cast<std::uint32_t>(
      pixel_index * kAgentStatusWaveFramesPerPixel);

  if (phase < pixel_phase) {
    const auto lead = pixel_phase - phase;
    if (lead >= kAgentStatusWaveFramesPerPixel) {
      return 0U;
    }
    return static_cast<std::uint8_t>(
        kAgentStatusWaveScaleMax -
        ((lead * kAgentStatusWaveScaleMax) /
         kAgentStatusWaveFramesPerPixel));
  }

  const auto lag = phase - pixel_phase;
  const auto tail_frames = static_cast<std::uint32_t>(
      kAgentStatusWaveTailPixels * kAgentStatusWaveFramesPerPixel);
  if (lag >= tail_frames) {
    return 0U;
  }
  return static_cast<std::uint8_t>(
      kAgentStatusWaveScaleMax -
      ((lag * (kAgentStatusWaveScaleMax - 1U)) / (tail_frames - 1U)));
}

inline bool agent_status_is_animated(AgentStatusState state) {
  return state != AgentStatusState::kIdle;
}

inline std::uint8_t agent_status_waiting_scanner_numerator(
    std::uint32_t elapsed_ms,
    std::uint8_t pixel_index,
    std::uint8_t pixel_count) {
  if (pixel_count == 0U || pixel_index >= pixel_count) {
    return 0U;
  }
  if (pixel_count == 1U) {
    return kAgentStatusWaveScaleMax;
  }

  const auto path_steps = static_cast<std::uint8_t>((pixel_count - 1U) * 2U);
  const auto step = static_cast<std::uint8_t>(
      (elapsed_ms / (kAgentStatusAnimationFrameMs *
                     kAgentStatusScannerFramesPerPixel)) %
      path_steps);
  const auto head = step < pixel_count
                        ? step
                        : static_cast<std::uint8_t>(path_steps - step);
  const auto distance = pixel_index > head ? pixel_index - head
                                           : head - pixel_index;
  if (distance == 0U) {
    return 16U;
  }
  if (distance == 1U) {
    return 6U;
  }
  if (distance == 2U) {
    return 2U;
  }
  return 0U;
}

inline std::uint8_t agent_status_completed_bloom_numerator(
    std::uint32_t elapsed_ms,
    std::uint8_t pixel_index,
    std::uint8_t pixel_count) {
  if (pixel_count == 0U || pixel_index >= pixel_count) {
    return 0U;
  }

  const auto center = static_cast<std::uint8_t>(pixel_count / 2U);
  const auto distance = pixel_index > center ? pixel_index - center
                                             : center - pixel_index;
  const auto max_distance = center > (pixel_count - 1U - center)
                                ? center
                                : static_cast<std::uint8_t>(
                                      pixel_count - 1U - center);
  const auto travel_frames = static_cast<std::uint8_t>(
      (max_distance + 1U) * kAgentStatusBloomFramesPerRing);
  const auto cycle_frames = static_cast<std::uint8_t>(
      travel_frames + kAgentStatusBloomPauseFrames);
  const auto phase = static_cast<std::uint8_t>(
      (elapsed_ms / kAgentStatusAnimationFrameMs) % cycle_frames);
  const auto ring = static_cast<std::uint8_t>(
      phase / kAgentStatusBloomFramesPerRing);

  if (ring <= max_distance) {
    if (distance == ring) {
      return 16U;
    }
    if (distance < ring) {
      const auto trail = static_cast<std::uint8_t>(ring - distance);
      return trail == 1U ? 6U : 2U;
    }
    return 0U;
  }
  if (ring == max_distance + 1U) {
    return distance == max_distance ? 7U : (distance + 1U) * 2U;
  }
  return 0U;
}

inline std::uint8_t agent_status_failed_pulse_numerator(
    std::uint32_t elapsed_ms) {
  const auto frame = static_cast<std::uint8_t>(
      (elapsed_ms / kAgentStatusAnimationFrameMs) %
      kAgentStatusFailedCycleFrames);
  if (frame < 3U) {
    constexpr std::uint8_t kRise[] = {6U, 12U, 16U};
    return kRise[frame];
  }
  if (frame < 6U) {
    constexpr std::uint8_t kFall[] = {16U, 9U, 3U};
    return kFall[frame - 3U];
  }
  if (frame >= 9U && frame < 12U) {
    constexpr std::uint8_t kRise[] = {6U, 12U, 16U};
    return kRise[frame - 9U];
  }
  if (frame >= 12U && frame < 15U) {
    constexpr std::uint8_t kFall[] = {16U, 9U, 3U};
    return kFall[frame - 12U];
  }
  return 0U;
}

struct AgentStatusCommand {
  AgentStatusState state = AgentStatusState::kIdle;
  std::uint8_t flags = 0;
  std::uint32_t sequence = 0;
  std::uint32_t ttl_ms = 0;
  std::uint32_t source_hash = 0;
};

inline bool agent_status_commands_equal(const AgentStatusCommand& left,
                                        const AgentStatusCommand& right) {
  return left.state == right.state && left.flags == right.flags &&
         left.sequence == right.sequence && left.ttl_ms == right.ttl_ms &&
         left.source_hash == right.source_hash;
}

inline std::uint32_t read_agent_status_u32_le(const std::uint8_t* data) {
  return static_cast<std::uint32_t>(data[0]) |
         (static_cast<std::uint32_t>(data[1]) << 8U) |
         (static_cast<std::uint32_t>(data[2]) << 16U) |
         (static_cast<std::uint32_t>(data[3]) << 24U);
}

inline bool decode_agent_status(const std::uint8_t* data,
                                std::size_t len,
                                AgentStatusCommand* out) {
  if (data == nullptr || out == nullptr || len < kAgentStatusPayloadLen ||
      data[0] != kAgentStatusProtocolVersion ||
      data[1] > static_cast<std::uint8_t>(AgentStatusState::kFailed)) {
    return false;
  }

  AgentStatusCommand command{};
  command.state = static_cast<AgentStatusState>(data[1]);
  command.flags = data[2];
  command.sequence = read_agent_status_u32_le(data + 4);
  command.ttl_ms = read_agent_status_u32_le(data + 8);
  command.source_hash = read_agent_status_u32_le(data + 12);
  if (command.ttl_ms > kAgentStatusMaxTtlMs) {
    command.ttl_ms = kAgentStatusMaxTtlMs;
  }
  if (command.state == AgentStatusState::kIdle) {
    command.ttl_ms = 0;
  }
  *out = command;
  return true;
}

inline bool agent_status_sequence_is_newer(std::uint32_t candidate,
                                           std::uint32_t baseline) {
  return candidate != baseline &&
         static_cast<std::int32_t>(candidate - baseline) > 0;
}

}  // namespace ai_keyboard
