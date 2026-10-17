import { Link, useLocation } from "react-router-dom";
import { useEffect } from "react";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error("404 Error: User attempted to access non-existent route:", location.pathname);
  }, [location.pathname]);

  // `dark` is applied per-page (see Index/Auth) rather than on <body>, so
  // without it this renders in the light palette — a white page with no way
  // back except a full reload.
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center">
        <h1 className="mb-4 text-4xl font-bold text-foreground">404</h1>
        <p className="mb-6 text-xl text-muted-foreground">Oops! Page not found</p>
        <div className="flex items-center justify-center gap-4 text-sm">
          <Link to="/" className="text-primary underline hover:text-primary/90">
            Return home
          </Link>
          <Link to="/app" className="text-primary underline hover:text-primary/90">
            Go to my squad
          </Link>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
