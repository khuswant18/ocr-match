import { useEffect, useState } from "react";
import { useSnackbar } from "notistack";
import httpRequest from "../../httpRequest";
import AppLayout from "../../components/AppLayout/AppLayout";
import { useStyles } from "./styles";
import UsersTable from "../../components/UsersTable/UsersTable";

const UsersPage = () => {
  const classes = useStyles();
  const userName = "Demo User";
  const [usersData, setUsersData] = useState([]);
  const [updatedUser, setUpdatedUser] = useState({});
  const { enqueueSnackbar } = useSnackbar();

  useEffect(() => {
    (async () => {
      try {
        const resp = await httpRequest.get(`${process.env.REACT_APP_BACKEND_URL}/get-users`);
        setUsersData(resp.data.users);
      } catch (error) {
        console.log("Error fetching users");
        enqueueSnackbar("Error fetching users", { variant: "error" });
      }
    })();
  }, [updatedUser, enqueueSnackbar]);

  const handleUserUpdated = (updatedUserID, updatedUserRole) => {
    setUpdatedUser({ updatedUserID, updatedUserRole });
  };

  return (
    <>
      <AppLayout userName={userName}>
        <div className={classes.tableContainer}>
          <UsersTable users={usersData} onUserUpdated={handleUserUpdated} />
        </div>
      </AppLayout>
    </>
  );
};

export default UsersPage;
