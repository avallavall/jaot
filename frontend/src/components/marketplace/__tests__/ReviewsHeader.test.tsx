import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

/**
 * A logged-out visitor was given the whole review form — five star controls and
 * two text fields — and it accepted everything they typed. Submit made no
 * request at all and pushed straight to /login, so the rating, the title and
 * the review were gone, with nothing offering to bring them back.
 *
 * The main action higher up the same page already says "Sign in to use this
 * model", so the page knows nobody is signed in before the typing starts.
 */

import { ReviewsHeader } from "../ModelDetailClient";

const WRITE_REVIEW = "marketplace-write-review";

describe("the review control over a model's reviews", () => {
  // CONTRACT-TEST: a stranger is sent to sign in before typing, not after
  it("offers sign-in, not the form, to somebody who is not signed in", () => {
    const onWrite = vi.fn();
    const onSignIn = vi.fn();
    render(
      <ReviewsHeader total={0} isAuthenticated={false} isOwnModel={false} onWrite={onWrite} onSignIn={onSignIn} />
    );

    const button = screen.getByTestId(WRITE_REVIEW);
    expect(button.textContent).toContain("signInToReview");

    fireEvent.click(button);

    expect(onSignIn).toHaveBeenCalledTimes(1);
    expect(onWrite).not.toHaveBeenCalled();
  });

  it("opens the form for somebody who is signed in", () => {
    const onWrite = vi.fn();
    const onSignIn = vi.fn();
    render(<ReviewsHeader total={3} isAuthenticated isOwnModel={false} onWrite={onWrite} onSignIn={onSignIn} />);

    const button = screen.getByTestId(WRITE_REVIEW);
    expect(button.textContent).toContain("writeReview");

    fireEvent.click(button);

    expect(onWrite).toHaveBeenCalledTimes(1);
    expect(onSignIn).not.toHaveBeenCalled();
  });

  it("counts the reviews once they have arrived, and not before", () => {
    const { rerender } = render(
      <ReviewsHeader total={null} isAuthenticated isOwnModel={false} onWrite={vi.fn()} onSignIn={vi.fn()} />
    );
    expect(screen.queryByText(/reviewCount/)).not.toBeInTheDocument();

    rerender(<ReviewsHeader total={7} isAuthenticated isOwnModel={false} onWrite={vi.fn()} onSignIn={vi.fn()} />);
    expect(screen.getByText(/reviewCount/)).toBeInTheDocument();
  });
  // CONTRACT-TEST: the author of a model is not offered a form the server
  // refuses. Both gates on a review — fork it, run it — are a minute's work on
  // your own model, so this is the only thing standing between an author and
  // five stars on their own listing.
  it("offers the author of the model an explanation instead of the form", () => {
    const onWrite = vi.fn();
    render(
      <ReviewsHeader
        total={2}
        isAuthenticated
        isOwnModel
        onWrite={onWrite}
        onSignIn={vi.fn()}
      />,
    );

    expect(screen.queryByTestId(WRITE_REVIEW)).not.toBeInTheDocument();
    expect(screen.getByText(/cannotReviewOwnModel/)).toBeInTheDocument();
    expect(onWrite).not.toHaveBeenCalled();
  });
});
