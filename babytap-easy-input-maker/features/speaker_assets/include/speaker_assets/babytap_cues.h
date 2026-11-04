#pragma once

#include <cstddef>
#include <cstdint>

#include "keyboard/agent_status.h"

namespace easy_input::speaker_assets {

struct BabytapCueSound {
  const std::uint8_t* encoded = nullptr;
  std::size_t encoded_bytes = 0U;
};

[[nodiscard]] BabytapCueSound babytap_cue_sound(
    ai_keyboard::AgentStatusCue cue);

}  // namespace easy_input::speaker_assets
