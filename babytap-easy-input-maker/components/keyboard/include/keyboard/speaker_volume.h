#pragma once

#include <algorithm>
#include <cstdint>
#include <limits>

namespace ai_keyboard {

inline constexpr std::uint8_t kSpeakerVolumeMaximumLevel = 5U;
inline constexpr std::uint8_t kSpeakerVolumeDefaultLevel = 3U;
inline constexpr std::uint8_t kSpeakerVolumeGainDenominator = 5U;

inline std::uint8_t clamp_speaker_volume_level(std::uint8_t level) {
  return std::min(level, kSpeakerVolumeMaximumLevel);
}

inline std::uint8_t step_speaker_volume(std::uint8_t level,
                                        int encoder_step) {
  level = clamp_speaker_volume_level(level);
  if (encoder_step < 0) {
    return std::min<std::uint8_t>(
        kSpeakerVolumeMaximumLevel,
        static_cast<std::uint8_t>(level + 1U));
  }
  if (encoder_step > 0) {
    return level == 0U ? 0U : static_cast<std::uint8_t>(level - 1U);
  }
  return level;
}

inline std::uint8_t speaker_volume_percent(std::uint8_t level) {
  return static_cast<std::uint8_t>(
      clamp_speaker_volume_level(level) * 20U);
}

inline std::int16_t scale_speaker_sample(std::int16_t sample,
                                         std::uint8_t level) {
  const auto numerator = clamp_speaker_volume_level(level);
  const auto scaled =
      (static_cast<std::int32_t>(sample) * numerator) /
      kSpeakerVolumeGainDenominator;
  return static_cast<std::int16_t>(std::clamp<std::int32_t>(
      scaled,
      std::numeric_limits<std::int16_t>::min(),
      std::numeric_limits<std::int16_t>::max()));
}

}  // namespace ai_keyboard
