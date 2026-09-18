/// router.tsx — route table (SPEC.md §7) + auth guard: redirects to /login
/// whenever the session check (GET /api/auth/me) fails with an
/// `unauthorized` ApiError.
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { useMe } from "./api/hooks";
import { Spinner } from "./components/Spinner";
import Login from "./screens/Login";
import Shops from "./screens/Shops";
import Setup from "./screens/Setup";
import Review from "./screens/Review";
import Generate from "./screens/Generate";
import Catalog from "./screens/Catalog";
import Settings from "./screens/Settings";

function RequireAuth() {
  const { data, isLoading, isError, error } = useMe();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }

  if (isError) {
    if (error instanceof ApiError && error.code === "unauthorized") {
      return <Navigate to="/login" replace />;
    }
    return (
      <div className="flex h-screen items-center justify-center text-sm text-danger-400">
        Could not reach the server. Please refresh.
      </div>
    );
  }

  if (!data) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Shops />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/shops/:id/setup" element={<Setup />} />
        <Route path="/shops/:id/review" element={<Review />} />
        <Route path="/shops/:id/generate" element={<Generate />} />
        <Route path="/shops/:id/catalog" element={<Catalog />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
