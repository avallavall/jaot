"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

/** Full-width skeleton matching the FeaturedCarousel hero height. */
export function CarouselSkeleton() {
  return (
    <div className="min-h-[280px] rounded-xl bg-muted/30 p-8 flex items-center">
      <div className="flex items-center gap-6 w-full">
        <Skeleton className="w-24 h-24 rounded-xl shrink-0" />

        <div className="flex flex-col gap-3 flex-1">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-96" />
          <Skeleton className="h-4 w-48" />
          <div className="flex gap-3 mt-2">
            <Skeleton className="h-6 w-20 rounded-full" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-24" />
          </div>
        </div>

        <Skeleton className="h-10 w-32 rounded-md shrink-0" />
      </div>
    </div>
  );
}

/** Single model card skeleton matching MarketplaceModelCard layout. */
export function ModelCardSkeleton() {
  return (
    <Card className="h-full flex flex-col gap-0 py-0 overflow-hidden">
      <Skeleton className="h-32 w-full rounded-none" />

      <CardHeader className="pb-2 pt-4">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-4 w-full mt-1" />
        <Skeleton className="h-4 w-2/3 mt-1" />
      </CardHeader>

      <CardContent className="mt-auto pb-4 pt-2">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Skeleton className="h-5 w-20 rounded-full" />
            <Skeleton className="h-4 w-10" />
          </div>
          <div className="flex items-center justify-between">
            <Skeleton className="h-5 w-12 rounded-full" />
            <Skeleton className="h-4 w-8" />
          </div>
          <Skeleton className="h-3 w-24" />
        </div>
      </CardContent>
    </Card>
  );
}

/** Grid of 6 model card skeletons matching the 3-column marketplace layout. */
export function ModelGridSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {Array.from({ length: 6 }, (_, i) => (
        <ModelCardSkeleton key={i} />
      ))}
    </div>
  );
}
