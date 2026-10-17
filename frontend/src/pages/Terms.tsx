import { Navbar } from "@/components/layout/Navbar";

export default function Terms() {
  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] text-white">
      <Navbar />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 pt-24 pb-16 prose prose-invert prose-sm">
        <h1>Terms of Service</h1>
        <p>Last updated: 18 July 2026</p>
        <p>
          FPLedge provides Fantasy Premier League analysis and recommendations for
          entertainment purposes. Projections are estimates, not guarantees — transfer
          and chip decisions are your own.
        </p>
        <p>
          The service is provided "as is" during beta, without warranty. We may change
          or discontinue features at any time.
        </p>
        <p>
          FPLedge is not affiliated with the Premier League or the official Fantasy
          Premier League game.
        </p>
      </main>
    </div>
  );
}
