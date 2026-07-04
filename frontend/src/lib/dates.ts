/**
 * Parse a timestamp coming from the JAOT API.
 *
 * The backend serializes naive UTC datetimes ("2026-07-04T09:08:27.717655" — no
 * `Z`, no offset). `new Date(<that>)` treats it as LOCAL time, shifting every
 * displayed date by the viewer's UTC offset (live bug 2026-07-04: "hace 2 horas"
 * on a run that just finished, from a UTC+2 browser). Strings that already carry
 * a timezone pass through untouched, so this stays correct if the backend ever
 * starts emitting offsets.
 */
export function apiDate(iso: string): Date {
  return new Date(/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
}
