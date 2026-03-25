import { Route, Routes } from "react-router-dom";

import HistoryPage from "../HistoryPage/HistoryPage";
import HomePage from "../HomePage/HomePage";
import UsersPage from "../UsersPage/UsersPage";
import MatchingPage from "../MatchingPage/MatchingPage";
import { useStyles } from "./styles";

const App = () => {
  const classes = useStyles();

  return (
    <div className={classes.appContainer}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/matching" element={<MatchingPage />} />
      </Routes>
    </div>
  );
};

export default App;
