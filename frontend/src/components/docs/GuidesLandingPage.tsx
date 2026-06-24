"use client";

import { useState } from "react";
import { Link } from "@/i18n/navigation";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { guidesByDomain } from "@/lib/docs/guide-data";

type Difficulty = "beginner" | "intermediate" | "advanced";

const DIFFICULTY_COLORS: Record<Difficulty, string> = {
  beginner:
    "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800",
  intermediate:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400 border-amber-200 dark:border-amber-800",
  advanced:
    "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-800",
};

const FILTERS: { label: string; value: Difficulty | null }[] = [
  { label: "All", value: null },
  { label: "Beginner", value: "beginner" },
  { label: "Intermediate", value: "intermediate" },
  { label: "Advanced", value: "advanced" },
];

export function GuidesLandingPage() {
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((filter) => (
          <button
            key={filter.label}
            onClick={() => setDifficulty(filter.value)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              difficulty === filter.value
                ? "bg-primary text-primary-foreground"
                : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
            }`}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {Object.entries(guidesByDomain).map(([domain, domainGuides]) => {
        const filtered = difficulty
          ? domainGuides.filter((g) => g.difficulty === difficulty)
          : domainGuides;

        if (filtered.length === 0) return null;

        return (
          <section key={domain}>
            <h2 className="text-xl font-bold mb-4">{domain}</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filtered.map((guide) => (
                <Link
                  key={guide.slug}
                  href={`/docs/guides/${guide.slug}`}
                  className="block no-underline"
                >
                  <Card className="h-full hover:border-primary/50 transition-colors">
                    <CardHeader>
                      <div className="flex items-center justify-between gap-2">
                        <CardTitle className="text-base">
                          {guide.title}
                        </CardTitle>
                        <Badge
                          variant="outline"
                          className={DIFFICULTY_COLORS[guide.difficulty]}
                        >
                          {guide.difficulty}
                        </Badge>
                      </div>
                      <CardDescription>{guide.description}</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>
                          {guide.templateCount}{" "}
                          {guide.templateCount === 1 ? "template" : "templates"}
                        </span>
                        <span>{guide.domain}</span>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
