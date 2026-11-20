fn main() {
        unsafe {
            let srv = self.srv.get_mut_unsafe();
            (srv.1)(cfg, &mut srv.0)
        }
}
