
// Password Strength Calculator
// Simple scoring: length + case mix + digits + special chars
// The visible label is translated by callers via auth.passwordStrength.{level}.

export type StrengthLevel = "weak" | "fair" | "strong";

export interface PasswordStrength {
  level: StrengthLevel;
  score: number;
  color: string;
}

export function getPasswordStrength(password: string): PasswordStrength {
  let score = 0;
  if (password.length >= 8) score += 20;
  if (password.length >= 12) score += 20;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 20;
  if (/\d/.test(password)) score += 20;
  if (/[^a-zA-Z0-9]/.test(password)) score += 20;

  if (score <= 40) return { level: "weak", score, color: "bg-red-500" };
  if (score <= 60) return { level: "fair", score, color: "bg-yellow-500" };
  return { level: "strong", score, color: "bg-green-500" };
}
