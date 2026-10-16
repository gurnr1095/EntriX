export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public retryAfter?: number) { super(message); }
}

const MESSAGES: Record<string, string> = {
  unauthenticated: "Please sign in to continue.",
  token_expired: "Your session expired. Please sign in again.",
  invalid_auth_token: "Your session is not valid. Please sign in again.",
  auth_unavailable: "Sign-in is temporarily unavailable. Try again in a minute.",
  forbidden: "You do not have permission to do that.",
  not_found: "We could not find that.",
  validation_error: "Please check the highlighted fields.",
  invalid_cursor: "The list changed. Reload the page.",
  missing_idempotency_key: "Something went wrong on our side. Please try again.",
  idempotency_in_progress: "Still working on your request...",
  already_registered: "You are already registered for this category.",
  category_full: "This category is full.",
  registration_closed: "Registration is not open for this event right now.",
  already_cancelled: "This registration was already cancelled.",
  already_checked_in: "Already checked in.",
  already_in_team: "You are already in a team for this category.",
  not_team_category: "This category is not a team category.",
  team_full: "This team is full.",
  team_cancelled: "This team was cancelled.",
  team_name_taken: "That team name is taken in this category. Choose another.",
  roster_locked: "The team is already registered, so members cannot change.",
  wrong_event: "This QR code belongs to a different event.",
  invalid_token: "That QR code is not valid.",
  slug_taken: "That web address (slug) is already used. Choose another.",
  category_name_taken: "A category with that name already exists in this event.",
  capacity_below_confirmed: "Capacity cannot be lower than the number already confirmed.",
  invalid_status_transition: "That status change is not allowed. Order is draft, published, closed.",
  account_conflict: "This email is linked to a different account. Contact the organizers.",
  rate_limited: "Too many attempts. Please wait a moment.",
  network: "Cannot reach the server. Check your connection.",
  timeout: "The server is taking too long. Please try again.",
  http_error: "Something went wrong. Please try again.",
};

const FALLBACK = "Something went wrong. Please try again.";

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.`
                              : (MESSAGES["rate_limited"] ?? FALLBACK);
    }
    if (error.code === "validation_error" && error.message) return error.message;
    return MESSAGES[error.code] ?? (error.status >= 500 ? FALLBACK : error.message);
  }
  return FALLBACK;
}
