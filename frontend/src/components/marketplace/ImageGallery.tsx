"use client";

import { useState } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";

interface ImageGalleryProps {
  screenshots: string[];
  modelName?: string;
}

export function ImageGallery({ screenshots, modelName = "" }: ImageGalleryProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const t = useTranslations("images");

  if (screenshots.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="relative w-full aspect-video rounded-lg overflow-hidden bg-muted">
        {/* unoptimized: screenshots come from a runtime-configured external CDN
            (STORAGE_CDN_URL, unknown at build time) and the backend already resizes +
            WebP-encodes them. Bypassing next/image optimization avoids the
            images.remotePatterns requirement that would otherwise throw at runtime. */}
        <Image
          src={screenshots[selectedIndex]}
          alt={t("modelScreenshot", { name: modelName })}
          fill
          priority={selectedIndex === 0}
          className="object-cover rounded-lg"
          sizes="(max-width: 768px) 100vw, 800px"
          unoptimized
        />
      </div>

      {/* Thumbnail strip (only if more than 1 screenshot) */}
      {screenshots.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {screenshots.map((url, index) => (
            <button
              key={index}
              type="button"
              onClick={() => setSelectedIndex(index)}
              className={`relative w-20 h-14 rounded overflow-hidden flex-shrink-0 transition-all ${
                index === selectedIndex
                  ? "ring-2 ring-primary ring-offset-2 ring-offset-background"
                  : "opacity-70 hover:opacity-100"
              }`}
            >
              <Image
                src={url}
                alt={t("modelScreenshotThumbnail", { index: index + 1, name: modelName })}
                fill
                className="object-cover"
                loading="lazy"
                sizes="80px"
                unoptimized
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
