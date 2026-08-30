import "@testing-library/jest-dom";

// jsdom does not implement object URLs; provide no-ops so download
// components can be tested in isolation.
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => "blob:jest";
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => undefined;
}