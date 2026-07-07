import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ConsentSettings } from "../types";

export function PrivacyControls() {
  const [settings, setSettings] = useState<ConsentSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get<ConsentSettings>("/consent-settings").then(setSettings).catch(() => {});
  }, []);

  async function update(patch: Partial<ConsentSettings>) {
    const updated = await api.patch<ConsentSettings>("/consent-settings", patch);
    setSettings(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  if (!settings) return null;

  return (
    <div className="border border-[var(--color-border)] rounded-lg p-4 bg-[var(--color-card)] space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Contribute anonymized data to improve coaching models</p>
          <p className="text-xs text-[var(--color-ink-soft)]">Off by default. You can change this any time.</p>
        </div>
        <input
          type="checkbox"
          checked={settings.allow_training_data_contribution}
          onChange={(e) => update({ allow_training_data_contribution: e.target.checked })}
          className="w-4 h-4"
        />
      </div>

      <div>
        <p className="text-sm font-medium mb-1">Default clip sharing</p>
        <select
          value={settings.default_clip_share_scope}
          onChange={(e) => update({ default_clip_share_scope: e.target.value })}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        >
          <option value="private">Private</option>
          <option value="friends">Friends</option>
          <option value="public">Public</option>
        </select>
      </div>

      <div>
        <p className="text-sm font-medium mb-1">Default profile visibility</p>
        <select
          value={settings.default_profile_share_scope}
          onChange={(e) => update({ default_profile_share_scope: e.target.value })}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        >
          <option value="private">Private</option>
          <option value="friends">Friends</option>
          <option value="public">Public</option>
        </select>
      </div>

      <div>
        <p className="text-sm font-medium mb-1">Video retention</p>
        <select
          value={settings.retention_policy}
          onChange={(e) => update({ retention_policy: e.target.value })}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        >
          <option value="keep_indefinitely">Keep indefinitely</option>
          <option value="delete_after_90d">Delete originals after 90 days</option>
          <option value="delete_after_1y">Delete originals after 1 year</option>
        </select>
      </div>

      {saved && <p className="text-xs text-[var(--color-good)]">Saved.</p>}
    </div>
  );
}
