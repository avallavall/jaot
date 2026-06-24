"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface ContactResponse {
  id: string;
  status: string;
  created_at: string;
}

export function ContactForm() {
  const t = useTranslations("contact");
  const { user } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  // Honeypot — never rendered visibly. Bots fill it; humans never see it.
  const [website, setWebsite] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Prefill from useAuth() on first render only; never clobber user typing.
  useEffect(() => {
    if (user) {
      if (!name && user.name) setName(user.name);
      if (!email && user.email) setEmail(user.email);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setErrorMsg(null);

    const browserLocale =
      typeof navigator !== "undefined" && navigator.language
        ? navigator.language.slice(0, 2)
        : null;

    try {
      await api.request<ContactResponse>("/api/v2/contact", {
        method: "POST",
        body: JSON.stringify({
          name,
          email,
          subject,
          message,
          website,
          locale: browserLocale,
        }),
      });
      setSubmitted(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          setErrorMsg(t("error.rateLimited"));
        } else if (err.status >= 400 && err.status < 500) {
          setErrorMsg(t("error.generic"));
        } else {
          setErrorMsg(t("error.serverError"));
        }
      } else {
        setErrorMsg(t("error.serverError"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-center">
        <h2 className="mb-2 text-xl font-semibold">{t("success.title")}</h2>
        <p className="text-muted-foreground">{t("success.body")}</p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {/* Honeypot — present in the DOM for bots, off-screen and unreachable for humans (D-01). */}
      <input
        type="text"
        name="website"
        value={website}
        onChange={(e) => setWebsite(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        style={{ display: "none" }}
      />

      <div className="space-y-2">
        <Label htmlFor="contact-name">{t("form.fields.name.label")}</Label>
        <Input
          id="contact-name"
          name="name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("form.fields.name.placeholder")}
          required
          maxLength={120}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-email">{t("form.fields.email.label")}</Label>
        <Input
          id="contact-email"
          name="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t("form.fields.email.placeholder")}
          required
          maxLength={320}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-subject">{t("form.fields.subject.label")}</Label>
        <Input
          id="contact-subject"
          name="subject"
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder={t("form.fields.subject.placeholder")}
          required
          maxLength={200}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-message">{t("form.fields.message.label")}</Label>
        <Textarea
          id="contact-message"
          name="message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={t("form.fields.message.placeholder")}
          required
          rows={6}
          maxLength={5000}
        />
      </div>

      {errorMsg && (
        <div
          role="alert"
          className="rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {errorMsg}
        </div>
      )}

      <Button type="submit" disabled={submitting} className="w-full">
        {submitting ? (
          <>
            <svg
              role="status"
              aria-hidden="true"
              className="size-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
              <path d="M12 2 a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" />
            </svg>
            {t("form.submit.submitting")}
          </>
        ) : (
          t("form.submit.button")
        )}
      </Button>
    </form>
  );
}
