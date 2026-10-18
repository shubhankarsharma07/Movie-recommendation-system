// ============================================================================
// CineMatch — auth.js
// Keeps the JWT and the signed-in user in localStorage.
// The password is never stored anywhere in the browser.
// ============================================================================

import { state, emit } from "./state.js";

const TOKEN_KEY = "cinematch_token";
const USER_KEY = "cinematch_user";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function isLoggedIn() {
  return !!getToken();
}

/** Called after login / register with the backend's response. */
export function setSession({ access_token, user }) {
  try {
    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch { /* storage full or blocked: the session lasts until reload */ }
  state.user = user;
  emit("auth:changed", user);
}

/** Keep the cached user fresh (e.g. after GET /api/auth/me). */
export function updateUser(user) {
  state.user = user;
  try { localStorage.setItem(USER_KEY, JSON.stringify(user)); } catch { /* ignore */ }
  emit("auth:changed", user);
}

export function getCachedUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch { /* ignore */ }
  state.user = null;
  state.ratings.clear();
  state.lastMix = null;
  emit("auth:changed", null);
}
