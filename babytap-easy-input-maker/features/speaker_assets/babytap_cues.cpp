#include "speaker_assets/babytap_cues.h"

namespace easy_input::speaker_assets {
namespace {

#define DECLARE_CUE(variable, file)                                      \
  extern const std::uint8_t variable##_start[] asm("_binary_" #file "_eiad_start"); \
  extern const std::uint8_t variable##_end[] asm("_binary_" #file "_eiad_end")

DECLARE_CUE(cue01, 01_timer_started);
DECLARE_CUE(cue02, 02_side_switched);
DECLARE_CUE(cue03, 03_bottle_prompt);
DECLARE_CUE(cue04, 04_solid_food_prompt);
DECLARE_CUE(cue05, 05_diaper_recorded);
DECLARE_CUE(cue06, 06_sleep_started);
DECLARE_CUE(cue07, 07_record_saved);
DECLARE_CUE(cue08, 08_cancelled);
DECLARE_CUE(cue09, 09_undone);
DECLARE_CUE(cue10, 10_status_idle);
DECLARE_CUE(cue11, 11_status_breastfeeding);
DECLARE_CUE(cue12, 12_status_sleep);
DECLARE_CUE(cue13, 13_status_waiting);
DECLARE_CUE(cue14, 14_failed);
DECLARE_CUE(cue15, 15_nothing_to_undo);

#undef DECLARE_CUE

BabytapCueSound sound(const std::uint8_t* begin, const std::uint8_t* end) {
  return {begin, static_cast<std::size_t>(end - begin)};
}

}  // namespace

BabytapCueSound babytap_cue_sound(ai_keyboard::AgentStatusCue cue) {
  switch (cue) {
    case ai_keyboard::AgentStatusCue::kTimerStarted:
      return sound(cue01_start, cue01_end);
    case ai_keyboard::AgentStatusCue::kSideSwitched:
      return sound(cue02_start, cue02_end);
    case ai_keyboard::AgentStatusCue::kBottlePrompt:
      return sound(cue03_start, cue03_end);
    case ai_keyboard::AgentStatusCue::kSolidFoodPrompt:
      return sound(cue04_start, cue04_end);
    case ai_keyboard::AgentStatusCue::kDiaperRecorded:
      return sound(cue05_start, cue05_end);
    case ai_keyboard::AgentStatusCue::kSleepStarted:
      return sound(cue06_start, cue06_end);
    case ai_keyboard::AgentStatusCue::kRecordSaved:
      return sound(cue07_start, cue07_end);
    case ai_keyboard::AgentStatusCue::kCancelled:
      return sound(cue08_start, cue08_end);
    case ai_keyboard::AgentStatusCue::kUndone:
      return sound(cue09_start, cue09_end);
    case ai_keyboard::AgentStatusCue::kStatusIdle:
      return sound(cue10_start, cue10_end);
    case ai_keyboard::AgentStatusCue::kStatusBreastfeeding:
      return sound(cue11_start, cue11_end);
    case ai_keyboard::AgentStatusCue::kStatusSleep:
      return sound(cue12_start, cue12_end);
    case ai_keyboard::AgentStatusCue::kStatusWaiting:
      return sound(cue13_start, cue13_end);
    case ai_keyboard::AgentStatusCue::kFailed:
      return sound(cue14_start, cue14_end);
    case ai_keyboard::AgentStatusCue::kNothingToUndo:
      return sound(cue15_start, cue15_end);
    case ai_keyboard::AgentStatusCue::kNone:
      return {};
  }
  return {};
}

}  // namespace easy_input::speaker_assets
