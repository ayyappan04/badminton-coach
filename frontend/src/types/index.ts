export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
}

export interface Video {
  id: string;
  original_filename: string;
  duration_seconds: number | null;
  fps: number | null;
  resolution_w: number | null;
  resolution_h: number | null;
  match_format: string;
  opponent_name: string | null;
  status: string;
  progress_pct: number;
  stage: string | null;
  processing_error: string | null;
  result_summary: string | null;
}

export interface TrackedPerson {
  id: string;
  track_id: number;
  role: string;
  first_frame: number;
  last_frame: number;
  track_confidence: number;
  sample_box?: { x: number; y: number; w: number; h: number; confidence: number } | null;
}

export interface Rally {
  rally_index: number;
  start_timestamp_s: number;
  end_timestamp_s: number;
  shot_count: number;
  confidence: number;
}

export interface Shot {
  timestamp_s: number;
  shot_type: string;
  side: string;
  contact_height: string;
  intent: string;
  outcome: string;
  confidence: number;
  tracked_person_id: string;
}

export interface CoachingInsight {
  timestamp_s: number;
  category: string;
  observed_action: string;
  likely_impact: string;
  correction: string;
  drill_id: string | null;
  confidence: number;
  limitations: string[];
}

export interface ScoreEntry {
  score: number | null;
  confidence: number;
}

export interface Scorecards {
  technique: ScoreEntry;
  footwork: ScoreEntry;
  positioning: ScoreEntry;
  stability: ScoreEntry;
}

export interface PlayStyleLabel {
  label: string;
  evidence: string;
  confidence: number;
}

export interface PlayerProfile {
  matches_analyzed_count: number;
  play_style_labels: PlayStyleLabel[];
  strengths: string[];
  weaknesses: string[];
  radar_scores: Record<string, ScoreEntry>;
  training_plan: {
    priority_areas?: string[];
    recommended_drill_tags?: string[];
    weekly_theme?: string;
  };
  message?: string;
}

export interface Drill {
  id: string;
  name: string;
  category: string;
  description: string;
  target_issue_tags: string[];
  difficulty: string;
}

export interface TechniquePhase {
  phase: string;
  description: string;
}

export interface TechniqueReference {
  shot_or_movement_name: string;
  singles_or_doubles_context: string;
  summary: string;
  phases: TechniquePhase[];
  common_beginner_mistakes: string[];
  advanced_variations: string[];
}

export interface ConsentSettings {
  allow_training_data_contribution: boolean;
  default_clip_share_scope: string;
  default_profile_share_scope: string;
  retention_policy: string;
}

// ---- V2 types ----

export interface RallyPhase {
  phase: string; // serve | return | attack | neutral | defense | ending
  start_s: number;
  end_s: number;
  confidence: number;
}

export interface RallyWithPhases extends Rally {
  phases: RallyPhase[];
  ending_shot_type: string | null;
  ending_track_role: string | null;
}

export interface QualityFactor {
  score: number;
  detail: string;
}

export interface QualityReport {
  score: number;
  pipeline_version?: string;
  usable: boolean;
  factors: Record<string, QualityFactor>;
  camera_cuts: number[];
  recommendations: string[];
}

export interface AnalyticsBlock {
  available?: boolean;
  confidence: number;
  basis: string;
  [key: string]: unknown;
}

export interface MatchAnalytics {
  feature_version: string;
  blocks: Record<string, AnalyticsBlock>;
}

export interface TechniqueScoreEntry {
  score: number | null;
  confidence: number;
  basis: string;
}

export interface CoachAnswer {
  answer: string;
  evidence: { video_id: string; timestamp_s: number; label: string }[];
  suggested_questions: string[];
  confidence: number | null;
}

export interface CompareSummary {
  video_id: string;
  filename: string;
  opponent_name: string | null;
  result_summary: string | null;
  quality_score: number | null;
  rally_count: number | null;
  avg_rally_duration_s: number | null;
  avg_shots_per_rally: number | null;
  total_shots: number | null;
  shot_variety: number | null;
  offensive_pct: number | null;
  defensive_pct: number | null;
  front_court_pct: number | null;
  confidence_note: string;
}

export interface TechniqueReferenceV2 extends TechniqueReference {
  category: string;
  checkpoints: string[];
  level_note: string | null;
  context_note: string | null;
  handedness: string;
}

export interface Club {
  club_id: string;
  name: string;
  description: string | null;
  member_count: number;
  my_role: string | null;
}
