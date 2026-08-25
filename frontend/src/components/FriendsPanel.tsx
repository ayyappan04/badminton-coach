import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../types";

interface Friend {
  friendship_id: string;
  user_id: string;
  display_name: string;
  status: string;
  requested_by_me: boolean;
}

export function FriendsPanel() {
  const [friends, setFriends] = useState<Friend[]>([]);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  function refresh() {
    api.get<Friend[]>("/friends").then(setFriends).catch(() => {});
  }

  useEffect(refresh, []);

  async function addFriend() {
    setMessage(null);
    try {
      const user = await api.get<User>(`/auth/users/lookup?email=${encodeURIComponent(email)}`);
      await api.post("/friends/requests", { to_user_id: user.id });
      setEmail("");
      setMessage(`Friend request sent to ${user.display_name}.`);
      refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Couldn't send request");
    }
  }

  async function accept(friendshipId: string) {
    await api.post(`/friends/requests/${friendshipId}/accept`);
    refresh();
  }

  return (
    <div>
      <div className="flex gap-2 mb-3">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Friend's email"
          className="border border-[var(--separator)] rounded-md px-3 py-1.5 text-sm flex-1"
        />
        <button onClick={addFriend} className="bg-[var(--accent)] text-white text-sm px-3 py-1.5 rounded-md">
          Add
        </button>
      </div>
      {message && <p className="text-xs text-[var(--text-secondary)] mb-3">{message}</p>}
      <div className="flex flex-col gap-2">
        {friends.map((f) => (
          <div key={f.friendship_id} className="flex items-center justify-between border border-[var(--separator)] rounded-lg px-3 py-2 bg-[var(--surface)]">
            <div>
              <p className="text-sm font-medium">{f.display_name}</p>
              <p className="text-xs text-[var(--text-secondary)]">
                {f.status === "pending" ? (f.requested_by_me ? "Request sent" : "Wants to connect") : "Friend"}
              </p>
            </div>
            {f.status === "pending" && !f.requested_by_me && (
              <button onClick={() => accept(f.friendship_id)} className="text-xs text-[var(--accent)] hover:underline">
                Accept
              </button>
            )}
          </div>
        ))}
        {friends.length === 0 && <p className="text-sm text-[var(--text-secondary)]">No connections yet.</p>}
      </div>
    </div>
  );
}
