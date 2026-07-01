import { AppSettings } from "../api/client";

/** Full AppSettings object for test mocks — override only what the test cares about. */
export const mkSettings = (over: Partial<AppSettings> = {}): AppSettings => ({
  painting_guides_enabled: false,
  show_nsfw: false,
  library_page_size: 48,
  filter_presets: [],
  recent_days: 7,
  library_sort: "name",
  scan_ignore_patterns: [],
  scan_tag_rules: [],
  scan_parts_names: [],
  guide_theme_defaults: {},
  ai_model: "",
  ai_effort: "low",
  part_categories_enabled: false,
  horizontal_parts_layout: false,
  ...over,
});
