import type { ReactNode } from "react";

export const metadata = { title: "ViMi Social", description: "Social publishing workspace" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
