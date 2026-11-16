// Every call to the server goes through here.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that it is running.");
  }
  if (response.ok) return response.json();

  let message = `The server answered with an error (${response.status}).`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // Not JSON; keep the generic message.
  }
  throw new ApiError(response.status, message);
}

const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

export const api = {
  me: () => request("/api/me"),
  login: (username, password) => post("/api/auth/login", { username, password }),
  logout: () => post("/api/auth/logout"),
  violations: (status, sort = "newest") =>
    request(
      `/api/violations?limit=100&sort=${sort}${status ? `&status=${encodeURIComponent(status)}` : ""}`,
    ),
  analytics: (days) => request(`/api/analytics?days=${days}`),
  violation: (id) => request(`/api/violations/${id}`),
  review: (id, decision, reason, note) =>
    post(`/api/violations/${id}/review`, { decision, reason: reason || null, note: note || null }),
  correctPlate: (id, plateText) => post(`/api/violations/${id}/plate`, { plate_text: plateText }),
  reviewOptions: () => request("/api/review-options"),
  changePassword: (currentPassword, newPassword) =>
    post("/api/me/password", { current_password: currentPassword, new_password: newPassword }),
  officers: () => request("/api/officers"),
  addOfficer: (officer) => post("/api/officers", officer),
  setOfficerActive: (id, active) => post(`/api/officers/${id}/active`, { active }),
  resetOfficerPassword: (id, password) => post(`/api/officers/${id}/password`, { password }),
};
