// Linear-expression parsing shared by the canvas deserializer and the canvas
// fidelity gate. The canvas can only represent LINEAR models — coefficient edges
// into constraint/objective nodes plus a numeric RHS — so everything here answers
// one question precisely: can this expression be represented as edges + RHS with
// nothing lost? Anything it cannot read exactly (nonlinear products, functions,
// parentheses, unknown syntax) parses to `null`, and the caller must treat the
// canvas as an unfaithful view of the model — never silently drop what it read.

export interface LinearTerm {
  coefficient: number;
  varName: string;
}

/** One side of a (in)equality: its variable terms plus its folded constant. */
export interface LinearSide {
  terms: LinearTerm[];
  constant: number;
}

export interface LinearConstraint {
  /** Combined terms with RHS variables moved left (negated), zero terms dropped. */
  terms: LinearTerm[];
  operator: "<=" | ">=" | "==";
  /** Folded numeric RHS: rhs constants minus lhs constants. */
  rhs: number;
}

const EPS = 1e-9;

// number | identifier | one of + - * — anything else fails the tokenize (and the
// expression is declared not linear-representable).
const TOKEN = /(\d+\.\d+|\d+\.|\.\d+|\d+|[A-Za-z_]\w*|[+\-*])/y;

type Token = { kind: "num"; value: number } | { kind: "ident"; name: string } | {
  kind: "op";
  op: "+" | "-" | "*";
};

function tokenize(text: string): Token[] | null {
  const tokens: Token[] = [];
  let pos = 0;
  while (pos < text.length) {
    if (/\s/.test(text[pos])) {
      pos++;
      continue;
    }
    TOKEN.lastIndex = pos;
    const match = TOKEN.exec(text);
    if (!match) return null; // unexpected character — not our grammar
    const raw = match[1];
    if (raw === "+" || raw === "-" || raw === "*") {
      tokens.push({ kind: "op", op: raw });
    } else if (/^[A-Za-z_]/.test(raw)) {
      tokens.push({ kind: "ident", name: raw });
    } else {
      tokens.push({ kind: "num", value: parseFloat(raw) });
    }
    pos = TOKEN.lastIndex;
  }
  return tokens;
}

/**
 * Parse one side of a constraint/objective as a linear expression, or `null`
 * when it is not exactly representable (nonlinear, parentheses, anything odd).
 * Accepts sign chains (`- -x`), explicit (`2*x`) and implicit (`2 x`)
 * coefficient products, and bare constants; folds constants into `constant`.
 */
export function parseLinearSide(text: string): LinearSide | null {
  const tokens = tokenize(text);
  if (tokens === null || tokens.length === 0) return null;

  const terms: LinearTerm[] = [];
  let constant = 0;
  let i = 0;
  for (;;) {
    let sign = 1;
    while (i < tokens.length && tokens[i].kind === "op") {
      const op = (tokens[i] as { op: string }).op;
      if (op === "*") return null; // stray product — not a term boundary
      if (op === "-") sign = -sign;
      i++;
    }
    if (i >= tokens.length) return null; // dangling sign (or empty expression)

    const tok = tokens[i];
    if (tok.kind === "num") {
      i++;
      const next = tokens[i];
      if (next && next.kind === "op" && next.op === "*") {
        const ident = tokens[i + 1];
        if (!ident || ident.kind !== "ident") return null; // "2 * 3" / "2 *" — not linear terms
        terms.push({ coefficient: sign * tok.value, varName: ident.name });
        i += 2;
      } else if (next && next.kind === "ident") {
        // implicit multiplication: "2 x"
        terms.push({ coefficient: sign * tok.value, varName: next.name });
        i += 2;
      } else {
        constant += sign * tok.value;
      }
    } else if (tok.kind === "ident") {
      i++;
      const next = tokens[i];
      if (next && next.kind === "op" && next.op === "*") return null; // "x*y" / "x*2" — nonlinear or unsupported
      terms.push({ coefficient: sign, varName: tok.name });
    } else {
      return null;
    }

    if (i >= tokens.length) break;
    const sep = tokens[i];
    if (sep.kind !== "op" || sep.op === "*") return null; // two terms with no +/- between
    // leave the sign for the next loop turn
  }
  return { terms, constant };
}

/** Sum duplicate variables and drop numerically-zero terms, preserving order. */
function combine(terms: LinearTerm[]): LinearTerm[] {
  const order: string[] = [];
  const byVar = new Map<string, number>();
  for (const term of terms) {
    if (!byVar.has(term.varName)) order.push(term.varName);
    byVar.set(term.varName, (byVar.get(term.varName) ?? 0) + term.coefficient);
  }
  return order
    .map((varName) => ({ varName, coefficient: byVar.get(varName)! }))
    .filter((t) => Math.abs(t.coefficient) > EPS);
}

/**
 * Parse a full linear constraint — variables allowed on BOTH sides, constants
 * anywhere — into the canvas-normal form `terms OP rhs` (RHS variables moved
 * left negated, constants folded right). `null` when any part is not exactly
 * representable, including chained comparisons.
 */
export function parseLinearConstraint(expr: string): LinearConstraint | null {
  let operator: "<=" | ">=" | "==";
  let splitIdx: number;
  if ((splitIdx = expr.indexOf("<=")) >= 0) {
    operator = "<=";
  } else if ((splitIdx = expr.indexOf(">=")) >= 0) {
    operator = ">=";
  } else if ((splitIdx = expr.indexOf("==")) >= 0) {
    operator = "==";
  } else {
    return null;
  }

  const lhs = parseLinearSide(expr.substring(0, splitIdx));
  // A second comparator in the remainder tokenizes to null ("a <= b <= c" declines).
  const rhs = parseLinearSide(expr.substring(splitIdx + 2));
  if (!lhs || !rhs) return null;

  const moved = rhs.terms.map((t) => ({ ...t, coefficient: -t.coefficient }));
  return {
    terms: combine([...lhs.terms, ...moved]),
    operator,
    rhs: rhs.constant - lhs.constant,
  };
}

function coefficientMapsEqual(a: LinearTerm[], b: LinearTerm[]): boolean {
  if (a.length !== b.length) return false;
  const byVar = new Map(a.map((t) => [t.varName, t.coefficient]));
  return b.every((t) => {
    const coeff = byVar.get(t.varName);
    return coeff !== undefined && Math.abs(coeff - t.coefficient) <= EPS;
  });
}

/**
 * Whether two constraint expressions denote the same linear constraint (term
 * order and constant placement ignored). Falls back to exact-string equality
 * when either side is not linear-parseable — an unreadable expression can only
 * be "the same" as itself, never assumed equivalent.
 */
export function constraintExpressionsEquivalent(a: string, b: string): boolean {
  const pa = parseLinearConstraint(a);
  const pb = parseLinearConstraint(b);
  if (!pa || !pb) return a.trim() === b.trim();
  return (
    pa.operator === pb.operator &&
    Math.abs(pa.rhs - pb.rhs) <= EPS &&
    coefficientMapsEqual(pa.terms, pb.terms)
  );
}

/** Same-linear-expression check for objectives (no comparator, constants count). */
export function linearExpressionsEquivalent(a: string, b: string): boolean {
  const pa = parseLinearSide(a);
  const pb = parseLinearSide(b);
  if (!pa || !pb) return a.trim() === b.trim();
  return (
    Math.abs(pa.constant - pb.constant) <= EPS &&
    coefficientMapsEqual(combine(pa.terms), combine(pb.terms))
  );
}
