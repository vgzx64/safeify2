            values: self.values.as_mut_ptr(),
        // we cannot move out of self because of the drop impl.
        let (ids, values) = unsafe {
            (ptr::read(&self.ids), ptr::read(&self.values))
        };
        mem::forget(self);
            ids: ids.into_iter(),
            values: values,
