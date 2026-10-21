/** Maps Better Auth client errors to friendly, non-revealing messages. */
export function authErrorMessage(error: {
  status?: number;
  code?: string;
  message?: string;
}): string {
  if (error.status === 429) return "Too many attempts. Please wait a minute and try again.";
  switch (error.code) {
    case "INVALID_EMAIL_OR_PASSWORD":
      return "Incorrect email or password.";
    case "USER_ALREADY_EXISTS":
    case "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL":
      return "An account with this email already exists. Try signing in instead.";
    case "PASSWORD_TOO_SHORT":
      return "Your password is too short.";
    case "PASSWORD_TOO_LONG":
      return "Your password is too long.";
    case "INVALID_PASSWORD":
      return "Your current password is incorrect.";
    default:
      return "Something went wrong. Please try again.";
  }
}

/** Errors Better Auth appends to the callback URL after a failed social sign-in. */
export function oauthErrorMessage(code: string | undefined): string | undefined {
  if (!code) return undefined;
  if (code === "account_not_linked") {
    return "This email is already registered with a password. Sign in with your password instead.";
  }
  return "Google sign-in did not complete. Please try again.";
}
