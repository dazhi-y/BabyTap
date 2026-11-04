idf_component_register(
  SRCS
    "diagnostic_link_anchor.cpp"
    "babytap_cues.cpp"
    "factory_boot_sound.cpp"
    "speaker_assets_protocol.cpp"
    "speaker_assets_flash_runner.cpp"
    "speaker_assets_runtime.cpp"
    "speaker_assets_session.cpp"
    "speaker_assets_store_executor.cpp"
    "speaker_assets_wifi_wire.cpp"
    "sound_asset_reader.cpp"
    "sound_asset_crypto.cpp"
    "sound_asset_format.cpp"
    "sound_asset_store.cpp"
    "esp_sound_bank_storage.cpp"
  INCLUDE_DIRS
    "include"
  REQUIRES
    esp_partition
    keyboard
  # BabyTap 提示音不随仓库提供：编译前请按 assets/babytap/README.md
  # 自行制作与各文件名对应的中文语音，放入 assets/babytap/。
  EMBED_FILES
    "assets/waytoagi.eiad"
    "assets/babytap/01_timer_started.eiad"
    "assets/babytap/02_side_switched.eiad"
    "assets/babytap/03_bottle_prompt.eiad"
    "assets/babytap/04_solid_food_prompt.eiad"
    "assets/babytap/05_diaper_recorded.eiad"
    "assets/babytap/06_sleep_started.eiad"
    "assets/babytap/07_record_saved.eiad"
    "assets/babytap/08_cancelled.eiad"
    "assets/babytap/09_undone.eiad"
    "assets/babytap/10_status_idle.eiad"
    "assets/babytap/11_status_breastfeeding.eiad"
    "assets/babytap/12_status_sleep.eiad"
    "assets/babytap/13_status_waiting.eiad"
    "assets/babytap/14_failed.eiad"
    "assets/babytap/15_nothing_to_undo.eiad"
  # Keep every adapter/core object in diagnostic ELF proofs. Production also
  # references the runtime directly through SpeakerAssetsSupervisor; retaining
  # the complete archive prevents a release-only adapter from silently falling
  # out of the final link graph.
  WHOLE_ARCHIVE
)
