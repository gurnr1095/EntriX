export interface ContactDetails {
  /** A person or team, for example "Sports Committee". */
  name: string;
  email: string;
  /** Any format people write numbers in; spaces and dashes are fine. */
  phone: string;
}

export const config = {
  apiUrl: "https://entrix-api-zn00.onrender.com",
  clerkPublishableKey: "pk_test_b3JnYW5pYy1jb3lvdGUtMjYzMC5jbGVyay5hY2NvdW50cy5kZXYk",
  /** Shown in the footer of every page. Leave a field empty to hide it; all empty hides the block. */
  contact: { name: "Altius, Sports Club", email: "grkr1095@gmail.com", phone: "9781078711" } as ContactDetails,
};
