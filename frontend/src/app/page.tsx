import { BentoSection } from "@/components/landing/BentoSection";
import { HeroSection } from "@/components/landing/HeroSection";
import { LandingHeader } from "@/components/landing/LandingHeader";
import { PipelineSection } from "@/components/landing/PipelineSection";
import { PortalSection } from "@/components/landing/PortalSection";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-obsidian text-white selection:bg-indigo-500/40">
      <LandingHeader />
      <main>
        <HeroSection />
        <PipelineSection />
        <BentoSection />
        <PortalSection />
      </main>
    </div>
  );
}
