// Tests for ImageGallery.tsx SC2 migration (next/image, localized alt, no raw <img>)
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock next/image since vitest/jsdom cannot render it natively
vi.mock("next/image", () => ({
  default: ({
    src,
    alt,
    fill,
    priority,
    className,
    sizes,
  }: {
    src: string;
    alt: string;
    fill?: boolean;
    priority?: boolean;
    className?: string;
    sizes?: string;
  }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      data-fill={fill ? "true" : undefined}
      data-priority={priority ? "true" : undefined}
      className={className}
      data-sizes={sizes}
    />
  ),
}));

// Import AFTER mocks
import { ImageGallery } from "../ImageGallery";

describe("ImageGallery — SC2 next/image migration", () => {
  const SCREENSHOTS = [
    "https://example.com/shot1.png",
    "https://example.com/shot2.png",
    "https://example.com/shot3.png",
  ];

  it("renders null when screenshots array is empty", () => {
    const { container } = render(
      <ImageGallery screenshots={[]} modelName="My Model" />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the main screenshot image with localized alt from modelName", () => {
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="Cool Model" />);
    // next-intl mock returns "images.modelScreenshot" with {name} replaced
    const mainImg = screen.getByAltText("images.modelScreenshot");
    expect(mainImg).toBeInTheDocument();
  });

  it("renders main image with fill and priority on first load (selectedIndex=0)", () => {
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="My Model" />);
    // The first screenshot is the initially selected one (index 0) → priority
    const imgs = screen.getAllByRole("img");
    // First img is the main image
    const mainImg = imgs[0];
    expect(mainImg).toHaveAttribute("data-fill", "true");
    expect(mainImg).toHaveAttribute("data-priority", "true");
  });

  it("renders thumbnail images with localized alt", () => {
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="My Model" />);
    // next-intl mock returns keys with interpolated values
    // thumbnail alt: "images.modelScreenshotThumbnail" with {index} and {name} replaced
    const thumbnails = screen.getAllByAltText(/images\.modelScreenshotThumbnail/);
    expect(thumbnails.length).toBe(3);
  });

  it("renders thumbnail strip only when more than 1 screenshot", () => {
    const { rerender } = render(
      <ImageGallery screenshots={["https://example.com/single.png"]} modelName="M" />
    );
    // With 1 screenshot, no thumbnail strip button
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    rerender(<ImageGallery screenshots={SCREENSHOTS} modelName="M" />);
    // With 3 screenshots, 3 thumbnail buttons
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("uses modelName prop (not alt prop) for gallery", () => {
    // The component should accept modelName, not alt
    // If ImageGallery still has alt prop this would pass it wrong
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="Test Model" />);
    // Verify the component renders (modelName prop is accepted)
    expect(screen.getByAltText("images.modelScreenshot")).toBeInTheDocument();
  });

  it("thumbnail images have fill attribute for next/image sizing", () => {
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="My Model" />);
    const thumbnails = screen.getAllByAltText(/images\.modelScreenshotThumbnail/);
    thumbnails.forEach((thumb) => {
      expect(thumb).toHaveAttribute("data-fill", "true");
    });
  });

  it("switching thumbnail updates selected index and main image src", async () => {
    const user = userEvent.setup();
    render(<ImageGallery screenshots={SCREENSHOTS} modelName="My Model" />);

    const buttons = screen.getAllByRole("button");
    // Click second thumbnail
    await user.click(buttons[1]);

    const mainImg = screen.getByAltText("images.modelScreenshot");
    expect(mainImg).toHaveAttribute("src", SCREENSHOTS[1]);
  });
});
