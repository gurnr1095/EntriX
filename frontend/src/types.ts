export type Role = "participant" | "volunteer" | "organizer" | "admin";
export type EventStatus = "draft" | "published" | "closed";
export type Participation = "individual" | "team";
export type RegStatus = "confirmed" | "waitlisted" | "cancelled" | "checked_in";
export type TeamStatus = "forming" | "registered" | "cancelled";

export interface User { id: string; email: string; name: string; college: string | null;
  roll_no: string | null; phone: string | null; role: Role; }
export interface UserPatch { name?: string; college?: string | null; roll_no?: string | null;
  phone?: string | null; }

export interface EventOut { id: string; slug: string; name: string; description: string | null;
  venue: string | null; starts_at: string; ends_at: string; reg_opens_at: string;
  reg_closes_at: string; status: EventStatus; }
export interface Category { id: string; event_id: string; name: string; sport: string;
  participation: Participation; team_size_min: number | null; team_size_max: number | null;
  capacity: number; confirmed_count: number; waitlist_enabled: boolean; seats_left: number; }
export interface EventDetail extends EventOut { categories: Category[]; }
export interface Page<T> { items: T[]; next_cursor: string | null; }

export interface EventCreate { slug: string; name: string; description?: string | null;
  venue?: string | null; starts_at: string; ends_at: string; reg_opens_at: string;
  reg_closes_at: string; }
export type EventPatch = Partial<Omit<EventCreate, "slug">> & { status?: EventStatus };
export interface CategoryCreate { name: string; sport: string; participation: Participation;
  team_size_min?: number | null; team_size_max?: number | null; capacity: number;
  waitlist_enabled?: boolean; }
export type CategoryPatch = Partial<Pick<CategoryCreate,
  "name" | "sport" | "capacity" | "waitlist_enabled">>;

export interface RegistrationResult { registration_id: string; status: RegStatus;
  waitlist_position?: number | null; }
// M6a adds the event/category/team fields to GET /me/registrations.
export interface MyRegistration { registration_id: string; category_id: string; status: RegStatus;
  waitlist_position: number | null; created_at: string; event_id: string; event_name: string;
  event_starts_at: string; venue: string | null; category_name: string; sport: string;
  team_id: string | null; team_name: string | null; }
// M6a: GET /me/teams
export interface MyTeam { id: string; name: string; status: TeamStatus; category_id: string;
  category_name: string; event_id: string; event_name: string; captain_id: string;
  invite_code: string | null; member_count: number; team_size_min: number;
  team_size_max: number; is_captain: boolean; }
export interface TeamMember { user_id: string; name: string; is_captain: boolean; }
export interface TeamOut { id: string; category_id: string; name: string; captain_id: string;
  status: TeamStatus; invite_code: string | null; }
export interface TeamDetail { id: string; category_id: string; name: string; captain_id: string;
  status: TeamStatus; invite_code: string | null; members: TeamMember[]; }

export interface CategoryStats { id: string; name: string; capacity: number; confirmed: number;
  waitlisted: number; checked_in: number; }
export interface EventStats { categories: CategoryStats[]; }
export interface Participant { id: string; name: string; email: string; college: string | null;
  roll_no: string | null; phone: string | null; }
export interface RegistrationRow { registration_id: string; status: RegStatus; category_id: string;
  category_name: string; team_name: string | null; participant: Participant; created_at: string;
  waitlisted_at: string | null; }
export interface CheckInResult { registration_id: string; status: RegStatus;
  already_checked_in: boolean; participant: { name: string; category: string }; }
