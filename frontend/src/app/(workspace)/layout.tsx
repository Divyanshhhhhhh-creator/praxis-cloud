import { AppHeader } from "@/components/workspace/AppHeader";

/** Crisp light enterprise chrome for /console, /policies, /approvals, /evals (no 3D, no heavy blur). */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <AppHeader />
      <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
