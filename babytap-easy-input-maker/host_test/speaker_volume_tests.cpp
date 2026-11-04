#include <cassert>
#include <cstdint>
#include <iostream>

#include "keyboard/speaker_volume.h"

namespace {

void test_six_levels_map_to_expected_percentages() {
  for (std::uint8_t level = 0; level <= 5; ++level) {
    assert(ai_keyboard::speaker_volume_percent(level) == level * 20U);
  }
  assert(ai_keyboard::speaker_volume_percent(200U) == 100U);
}

void test_clockwise_increases_and_counterclockwise_decreases() {
  assert(ai_keyboard::step_speaker_volume(3U, -1) == 4U);
  assert(ai_keyboard::step_speaker_volume(3U, 1) == 2U);
  assert(ai_keyboard::step_speaker_volume(5U, -1) == 5U);
  assert(ai_keyboard::step_speaker_volume(0U, 1) == 0U);
  assert(ai_keyboard::step_speaker_volume(3U, 0) == 3U);
}

void test_pcm_scaling_is_bounded_and_supports_mute() {
  assert(ai_keyboard::scale_speaker_sample(32767, 0U) == 0);
  assert(ai_keyboard::scale_speaker_sample(10000, 1U) == 2000);
  assert(ai_keyboard::scale_speaker_sample(-10000, 3U) == -6000);
  assert(ai_keyboard::scale_speaker_sample(32767, 5U) == 32767);
  assert(ai_keyboard::scale_speaker_sample(-32768, 5U) == -32768);
}

}  // namespace

int main() {
  test_six_levels_map_to_expected_percentages();
  test_clockwise_increases_and_counterclockwise_decreases();
  test_pcm_scaling_is_bounded_and_supports_mute();
  std::cout << "speaker_volume_tests passed\n";
  return 0;
}
