import { Route, Routes } from "react-router-dom";

import HistoryPage from "../HistoryPage/HistoryPage";
import HomePage from "../HomePage/HomePage";
import MatchingPage from "../MatchingPage/MatchingPage";
import PsrMatchPage from "../PsrMatchPage/PsrMatchPage";
import { useStyles } from "./styles";

const App = () => {
  const classes = useStyles();

  return (
    <div className={classes.appContainer}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/matching" element={<MatchingPage />} />
        <Route path="/psr-match" element={<PsrMatchPage />} />
      </Routes>
    </div>
  );
};

export default App;
