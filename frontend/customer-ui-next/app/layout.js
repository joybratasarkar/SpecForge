import './globals.css';
import Providers from './providers';

export const metadata = {
  title: 'SpecForge QA Console',
  description: 'Minimal operations console for QA agent runs, reports, and logs.'
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
