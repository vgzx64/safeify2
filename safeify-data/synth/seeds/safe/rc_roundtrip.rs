use std::rc::Rc;

fn $N() -> $T {
    let a = Rc::new($LIT);
    let b = a.clone();
    *b
}
