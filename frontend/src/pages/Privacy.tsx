import { Navbar } from "@/components/layout/Navbar";

export default function Privacy() {
  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] text-white">
      <Navbar />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 pt-24 pb-16 prose prose-invert prose-sm">
        <h1>Privacy Policy</h1>
        <p>Last updated: 18 July 2026</p>
        <h2>What we store</h2>
        <ul>
          <li>Your email address and authentication data, managed by Supabase.</li>
          <li>Your FPL team (entry) ID and plan tier, stored in our database.</li>
          <li>Locally on your device: your selected gameweek and squad preferences (browser storage).</li>
        </ul>
        <h2>What we don't do</h2>
        <ul>
          <li>We don't sell your data.</li>
          <li>We don't access your FPL account — we only read public FPL API data for the team ID you provide.</li>
        </ul>
        <h2>Deletion</h2>
        <p>
          Email zn.aianalytics@gmail.com to delete your account and all associated data.
        </p>
      </main>
    </div>
  );
}
