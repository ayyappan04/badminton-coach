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
  share_progress_with_club: boolean;
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

// ---- Phase 3 types ----

export interface OverlayLandmark {
  name: string;
  x: number;
  y: number;
  z: number;
  visibility: number;
}

export interface OverlayManifest {
  court: { corners_px: number[][]; method: string; confidence: number };
  boxes_by_frame: Record<string, { track_id: number; role: string; x: number; y: number; w: number; h: number; confidence: number }[]>;
  poses_by_frame: Record<string, { track_id: number; landmarks: OverlayLandmark[]; confidence: number }[]>;
  shuttle_by_frame: Record<string, { x: number; y: number; confidence: number }>;
  shuttle_trail: { frame_index: number; x: number; y: number }[];
}

export interface DoublesRotationBlock extends AnalyticsBlock {
  formation_split?: { front_back_pct: number; side_by_side_pct: number };
  rotation?: {
    transitions_tracked: number;
    avg_rotation_delay_s: number | null;
    attacks_started_side_by_side: number;
    missed_rotations: number;
  };
  spacing?: { overlap_pct: number; wide_gap_pct: number; open_middle_in_defense_pct: number | null };
  findings?: { finding: string; suggestion: string }[];
}

export interface ClubMember {
  user_id: string;
  display_name: string;
  role: string;
  shares_progress: boolean;
  development_score?: number | null;
  matches_analyzed?: number;
  top_style?: string | null;
}

export interface ClubDetail {
  club_id: string;
  name: string;
  description: string | null;
  members: ClubMember[];
  team_dashboard: {
    sharing_members: number;
    avg_development_score: number | null;
    note: string;
  };
}

export interface SharedClipItem {
  clip_id: string;
  video_id: string;
  created_by_user_id: string;
  clip_start_s: number;
  clip_end_s: number;
  visibility: string;
  caption: string | null;
}
