import { Topbar } from "./components/Topbar";
import { useJobPoll } from "./hooks/useJobPoll";
import { Browse } from "./pages/Browse";
import { NewJob } from "./pages/NewJob";
import { useStore } from "./store";

export default function App() {
  const page = useStore((s) => s.page);

  // Mounted here rather than inside NewJob, so a job keeps being polled while
  // you are reading the Browse tables.
  useJobPoll();

  return (
    <>
      <Topbar />
      {page === "browse" ? <Browse /> : <NewJob />}
    </>
  );
}
