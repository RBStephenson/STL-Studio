import { describe, it, expect } from "vitest";
import { joinLibraryPath } from "./libraryPath";

describe("joinLibraryPath (STUDIO-452)", () => {
  it("joins under a Windows root with backslashes", () => {
    expect(joinLibraryPath("F:\\3DModelLibrary", "3DMOONN", "Hilda")).toBe(
      "F:\\3DModelLibrary\\3DMOONN\\Hilda",
    );
  });

  it("joins under a POSIX root with forward slashes", () => {
    expect(joinLibraryPath("/library", "Abe3D", "Cobra Commander")).toBe(
      "/library/Abe3D/Cobra Commander",
    );
  });

  it("does not double up a separator the root already ends with", () => {
    expect(joinLibraryPath("F:\\3DModelLibrary\\", "3DMOONN", "Hilda")).toBe(
      "F:\\3DModelLibrary\\3DMOONN\\Hilda",
    );
    expect(joinLibraryPath("/library/", "Abe3D", "Zarana")).toBe("/library/Abe3D/Zarana");
  });

  it("keeps a Windows drive root usable as a root", () => {
    expect(joinLibraryPath("F:\\", "3DMOONN", "Hilda")).toBe("F:\\3DMOONN\\Hilda");
  });

  it("keeps the leading slash of a POSIX filesystem root", () => {
    expect(joinLibraryPath("/", "Abe3D", "Zarana")).toBe("/Abe3D/Zarana");
  });

  it("follows a mixed-separator root's Windows convention rather than adding a third", () => {
    expect(joinLibraryPath("C:/Models\\Packs", "Abe3D", "Zarana")).toBe(
      "C:/Models\\Packs\\Abe3D\\Zarana",
    );
  });

  it("skips empty segments instead of emitting a doubled separator", () => {
    expect(joinLibraryPath("/library", "", "Zarana")).toBe("/library/Zarana");
  });

  it("returns the root alone when there are no segments to append", () => {
    expect(joinLibraryPath("F:\\3DModelLibrary")).toBe("F:\\3DModelLibrary");
    expect(joinLibraryPath("F:\\3DModelLibrary\\")).toBe("F:\\3DModelLibrary");
  });

  it("does not invent a root when the root is empty", () => {
    expect(joinLibraryPath("", "Abe3D", "Zarana")).toBe("Abe3D/Zarana");
  });
});
