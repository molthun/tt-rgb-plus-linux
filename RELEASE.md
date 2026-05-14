# Release Checklist

1. Test locally:

   ```bash
   python3 -m py_compile tt_rgb_plus.py
   ./build_deb.sh 1.1.1
   dpkg-deb -I dist/tt-rgb-plus_1.1.1_all.deb
   dpkg-deb -c dist/tt-rgb-plus_1.1.1_all.deb
   ```

2. Commit source files only. `build/`, `dist/`, and `.deb` files are ignored.

3. Tag release:

   ```bash
   git tag -a v1.1.1 -m "tt-rgb-plus 1.1.1"
   git push origin main --tags
   ```

4. Upload the `.deb` to GitHub Releases, not directly to the git repository.
