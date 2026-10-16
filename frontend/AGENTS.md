<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

## EntriX architecture
- Keep TanStack Start and its file router; the platform requires it in place of react-router-dom.
- Shared navigation and Clerk provider wrap the root Outlet so all placeholder pages share the shell.
- Read the Clerk publishable key from src/config.ts; application data must come only from the external REST API.
- Keep QR packages installed but unused until requested; this phase has no registration or scanning logic.
- Organizer detail uses a trailing-underscore route to remain independent of the organizer placeholder page.
