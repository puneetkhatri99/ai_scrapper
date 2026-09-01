import { Footer } from "./components/Footer";
import { Topbar } from "./components/Topbar";
import { useJobPoll } from "./hooks/useJobPoll";
import { Browse } from "./pages/Browse";
import { Companies } from "./pages/Companies";
import { Company } from "./pages/Company";
import { NewJob } from "./pages/NewJob";
import { useStore } from "./store";

// Still no router (rules.md G29): `page` is a store key, and this is the whole
// of the switch. NewJob is the fallback, so an unknown key lands somewhere.
const PAGES = { browse: Browse, companies: Companies, company: Company };

export default function App() {
  const page = useStore((s) => s.page);
  const Page = PAGES[page] ?? NewJob;

  // Mounted here rather than inside NewJob, so a job keeps being polled while
  // you are reading the Browse tables.
  useJobPoll();

  return (
    <>
      <Topbar />
      <Page />
      <Footer />
    </>
  );
}
