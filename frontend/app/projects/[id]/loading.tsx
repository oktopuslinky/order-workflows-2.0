// Instant navigation fallback for /projects/[id] — same skeleton the page
// itself shows while the project query is in flight, so the two states blend.
import { WorkspaceSkeleton } from "@/components/Skeleton";

export default function Loading() {
  return <WorkspaceSkeleton />;
}
